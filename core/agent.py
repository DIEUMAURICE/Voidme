import os
import yaml
import json
import logging
import asyncio
import threading
import uuid
import sys
try:
    import psutil
except ImportError:
    psutil = None
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from core.models import LLMAdapter
from core.tools import ToolManager
from core.server import start_web_server, push_notification
from core.memory import MemoryManager
from core.profile import UserProfile

# Disable noisy logs
logging.basicConfig(level=logging.ERROR)

class VoidClawAgent:
    def __init__(self, config_path):
        self.config_path = config_path
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.workspace_dir = os.path.join(self.base_dir, self.config.get('workspace_dir', 'workspace'))
        self.chats_dir = os.path.join(self.base_dir, 'common', 'chats')
        self.tasks_path = os.path.join(self.base_dir, 'common', 'tasks.yaml')
        self.profile_path = os.path.join(self.base_dir, 'common', 'user_profile.json')
        
        if not os.path.exists(self.chats_dir):
            os.makedirs(self.chats_dir)
        
        # Initialisation de la mémoire et du profil
        self.memory = MemoryManager(persist_dir=os.path.join(self.base_dir, 'common', 'memory_db'))
        self.profile = UserProfile(self.profile_path)
        
        self.model = LLMAdapter(self.config)
        self.tools = ToolManager(self.workspace_dir)
        self.tools.set_agent(self) # Allow tools to access agent
        
        self.system_prompt = self._load_system_prompt()
        self.history = [] 
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.start_time = datetime.now()
        self.total_tokens = 0
        self.tool_usage = {}
        self.interrupted = False

        # Scheduler
        try:
            self.scheduler = AsyncIOScheduler()
        except Exception as e:
            from datetime import timezone
            self.scheduler = AsyncIOScheduler(timezone=timezone.utc)
        
        self._load_tasks()

        self.tg_app = None
        self.last_tg_chat_id = None

        # UI Elements (Orange Rebrand)
        self.LOGO = "ЁТЖЩ"
        self.ORANGE = '\033[38;5;214m'
        self.AMBER = '\033[93m'
        self.SLATE = '\033[90m'
        self.GREEN = '\033[92m'
        self.RED = '\033[91m'
        self.RESET = '\033[0m'
        self.BOLD = '\033[1m'
        self.DIM = '\033[2m'

    def reload_config(self):
        with open(self.config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        self.model = LLMAdapter(self.config)
        self.system_prompt = self._load_system_prompt()

    def clear_session(self):
        self.history = []
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        return "Session reset. Memory cleared."

    def get_dashboard_stats(self):
        uptime = str(datetime.now() - self.start_time).split('.')[0]
        jobs = self.scheduler.get_jobs()
        active_tasks = [{"id": j.id, "trigger": str(j.trigger), "instruction": j.args[2]} for j in jobs]
        
        activity_data = [0] * 7
        try:
            for f in os.listdir(self.chats_dir):
                if f.endswith('.md'):
                    stats = os.stat(os.path.join(self.chats_dir, f))
                    day_idx = datetime.fromtimestamp(stats.st_mtime).weekday()
                    activity_data[day_idx] += 1
        except: pass

        cpu_usage = 0.0
        ram_usage = 0.0
        if psutil:
            try:
                cpu_usage = psutil.cpu_percent()
                ram_usage = psutil.virtual_memory().percent
            except PermissionError:
                pass
            except Exception:
                pass
        ws_files = 0
        ws_size = 0
        try:
            for root, _, files in os.walk(self.workspace_dir):
                ws_files += len(files)
                ws_size += sum(os.path.getsize(os.path.join(root, name)) for name in files)
        except: pass

        return {
            "uptime": uptime,
            "total_tokens": self.total_tokens,
            "active_tasks": active_tasks,
            "activity": activity_data,
            "tool_usage": self.tool_usage,
            "system": {"cpu": cpu_usage, "ram": ram_usage},
            "workspace": {"files": ws_files, "size": round(ws_size / (1024 * 1024), 2)},
            "provider": self.config['default_provider'],
            "model": self.config[self.config['default_provider']]['model'],
            "channels": ["Terminal", "Web UI"] + (["Telegram"] if self.tg_app else [])
        }

    def get_settings(self):
        user_md_path = os.path.join(self.base_dir, 'common', 'user.md')
        prompt = ""
        if os.path.exists(user_md_path):
            with open(user_md_path, 'r', encoding='utf-8') as f:
                prompt = f.read()
        
        provider = self.config.get('default_provider', 'ollama')
        temp = self.config.get(provider, {}).get('temperature', 0.7)
        
        return {
            "system_prompt": prompt,
            "temperature": temp
        }

    def _load_tasks(self):
        if os.path.exists(self.tasks_path):
            with open(self.tasks_path, 'r') as f:
                tasks = yaml.safe_load(f) or []
                for task in tasks:
                    self.add_scheduled_task(task['type'], task['args'], task['instruction'], save=False)

    def _save_tasks(self):
        tasks = []
        for job in self.scheduler.get_jobs():
            tasks.append({
                'type': job.args[0],
                'args': job.args[1],
                'instruction': job.args[2]
            })
        with open(self.tasks_path, 'w') as f:
            yaml.dump(tasks, f)

    def add_scheduled_task(self, trigger_type, trigger_args, instruction, save=True):
        try:
            if trigger_type == 'cron':
                trigger = CronTrigger.from_crontab(trigger_args)
            elif trigger_type == 'interval':
                if trigger_args.endswith('s'):
                    trigger = IntervalTrigger(seconds=int(trigger_args[:-1]))
                elif trigger_args.endswith('m'):
                    trigger = IntervalTrigger(minutes=int(trigger_args[:-1]))
                else:
                    trigger = IntervalTrigger(minutes=int(trigger_args))
            else:
                return f"Error: Unsupported trigger type {trigger_type}"
            
            task_id = str(uuid.uuid4())[:8]
            self.scheduler.add_job(
                self.execute_scheduled_task,
                trigger,
                args=[trigger_type, trigger_args, instruction],
                id=task_id
            )
            if save: self._save_tasks()
            return f"Success: Task {task_id} scheduled ({trigger_type}: {trigger_args})"
        except Exception as e:
            return f"Error scheduling task: {str(e)}"

    def remove_scheduled_task(self, identifier):
        try:
            try:
                self.scheduler.remove_job(identifier)
                self._save_tasks()
                return f"Success: Task ID {identifier} removed."
            except:
                pass

            jobs = self.scheduler.get_jobs()
            removed_count = 0
            for job in jobs:
                instruction = job.args[2].lower()
                if identifier.lower() in instruction:
                    self.scheduler.remove_job(job.id)
                    removed_count += 1
            
            if removed_count > 0:
                self._save_tasks()
                return f"Success: Removed {removed_count} task(s) matching '{identifier}'."
            
            return f"Error: No task found matching '{identifier}'."
        except Exception as e:
            return f"Error removing task: {str(e)}"

    async def execute_scheduled_task(self, t_type, t_args, instruction):
        try:
            self.system_prompt = self._load_system_prompt()
            print(f"\n{self.ORANGE}{self.BOLD}тП░ AUTONOMOUS TASK TRIGGERED{self.RESET} {self.DIM}┬╗{self.RESET} {instruction}")
            reply = await self.process_message(f"AUTONOMOUS SCHEDULED TASK: {instruction}", source="AUTO")
            
            if reply:
                try:
                    from core.server import push_notification
                    push_notification(f"тП░ {reply}")
                    print(f"{self.GREEN}{self.BOLD}ЁЯСБ  NOTIFIED{self.RESET} {self.DIM}┬╗{self.RESET} Web UI")
                except Exception as e:
                    print(f"Web Notification Error: {e}")

                if self.tg_app and self.last_tg_chat_id:
                    try:
                        await self.tg_app.bot.send_message(chat_id=self.last_tg_chat_id, text=f"ЁЯФФ {reply}")
                        print(f"{self.GREEN}{self.BOLD}ЁЯСБ  NOTIFIED{self.RESET} {self.DIM}┬╗{self.RESET} Telegram")
                    except Exception as e:
                        print(f"Telegram Notification Error: {e}")
        except Exception as e:
            import traceback
            print(f"\n{self.RED}{self.BOLD}[!] CRITICAL ERROR IN SCHEDULED TASK:{self.RESET} {e}")
            traceback.print_exc()

    def _load_system_prompt(self):
        user_md_path = os.path.join(self.base_dir, 'common', 'user.md')
        if not os.path.exists(user_md_path):
            with open(user_md_path, 'w', encoding='utf-8') as f:
                f.write("# User Profile\n- Initialized")
                
        with open(user_md_path, 'r', encoding='utf-8') as f:
            user_content = f.read()
        
        current_time = datetime.now().strftime("%A, %B %d, %Y, %H:%M:%S")
        profile = self.profile.get()
        
        # Construire un prompt système enrichi
        profile_text = f"""
Profil utilisateur :
- Nom : {profile.get('name', 'User')}
- Humeur actuelle : {profile.get('mood', 'neutral')}
- Faits connus : {', '.join(profile.get('facts', [])[:10])}
- Préférences : {json.dumps(profile.get('preferences', {}), indent=2)}
- Nombre d'interactions : {profile.get('interaction_count', 0)}
"""
        
        return f"""
{user_content}

{profile_text}

Tu es NETFLASH CODE AGENT, un agent autonome évolutif, conçu pour assister l'utilisateur de manière proactive.

**Mémoire** : Tu as accès à une mémoire à long terme. Avant de répondre, tu recherches les souvenirs pertinents. Après chaque interaction, tu résumes l'échange et l'ajoutes à ta mémoire.

**Planification** : Pour les tâches complexes, tu peux proposer un plan en plusieurs étapes. Utilise le format JSON avec une clé "plan" contenant une liste d'outils à exécuter séquentiellement.

**Auto-amélioration** : Tu peux modifier ton propre prompt système (fichier user.md) si tu juges que cela améliore tes performances. Tu peux aussi suggérer des modifications de code, mais tu dois demander confirmation à l'utilisateur.

**Proactivité** : Tu peux te programmer pour exécuter des tâches périodiques. Analyse l'état du système et propose des actions pertinentes.

**Règles** :
- Toujours vérifier les autorisations avant d'effectuer des actions sensibles.
- En cas d'échec, réessayer avec une stratégie alternative.
- Expliquer clairement tes décisions et tes observations.

Système Time : {current_time}

Outils disponibles (réponds en JSON si tu as besoin d'un outil ou d'un plan) :
- list_files, list_files_recursive, get_workspace_tree, read_file, write_file, delete_file, create_directory, move_file, rename_file
- web_search: query
- update_user_profile: info (Save facts about the user here)
- update_config: key, value
- fetch_youtube_transcript: url
- fetch_weather: city
- web_scrape: url
- python_sandbox: code
- download_youtube: url, format_type (video/audio)
- convert_media: input_file, output_format
- local_rag_search: query
- schedule_task: trigger_type ('cron' or 'interval'), schedule_args, instruction
- list_tasks, remove_task, remove_all_tasks
- remind_me: message, time_args
- stop_reminders: keyword
- android_control: action, target
- edit_system_prompt: new_content (modifier le prompt système)
- edit_agent_code: file_path, new_code (avec précaution)
- get_user_profile, update_user_profile

Important : Si tu souhaites envoyer un fichier à l'utilisateur (via Telegram), utilise le préfixe "SEND_FILE:" suivi du chemin absolu.
"""

    def log_chat(self, role, message):
        log_file = os.path.join(self.chats_dir, f"session_{self.session_id}.md")
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"### [{timestamp}] {role}\n{message}\n\n")

    def _parse_json(self, response):
        try:
            return json.loads(response)
        except:
            if "```json" in response:
                content = response.split("```json")[1].split("```")[0].strip()
                try: return json.loads(content)
                except: pass
            elif "```" in response:
                content = response.split("```")[1].split("```")[0].strip()
                try: return json.loads(content)
                except: pass
        return None

    async def process_message(self, user_input, source="TERM"):
        prefix = "ЁЯСд YOU" if source == "TERM" else f"ЁЯСд YOU ({source})"
        context_history = []
        
        if source != "AUTO":
            print(f"\n{self.AMBER}{self.BOLD}{prefix}{self.RESET} {self.DIM}┬╗{self.RESET} {user_input}")
            self.log_chat(f"USER ({source})", user_input)
            self.history.append({"role": "user", "content": user_input})
            self.total_tokens += len(user_input) // 4
            context_history = self.history[-10:]

        # Récupération des souvenirs pertinents
        relevant_memories = self.memory.retrieve(user_input, top_k=3)
        memory_context = ""
        if relevant_memories:
            memory_context = "Souvenirs pertinents :\n" + "\n".join([m['text'] for m in relevant_memories])

        context = "\n".join([f"{m['role']}: {m['content']}" for m in context_history])
        if memory_context:
            context = memory_context + "\n" + context
        if source == "AUTO":
            context = f"SYSTEM: {user_input}"
        
        final_response = None
        
        for _ in range(5):
            response = await self.model.generate_response(context, self.system_prompt)
            tool_call = self._parse_json(response)
            
            if tool_call and isinstance(tool_call, dict) and "plan" in tool_call:
                # Exécution d'un plan
                plan = tool_call["plan"]
                observations = []
                for step in plan:
                    tool_name = step.get("tool")
                    args = step.get("args", {})
                    if not tool_name:
                        continue
                    print(f"\n{self.ORANGE}{self.BOLD}ЁЯЫа  PLAN STEP{self.RESET} {self.DIM}┬╗{self.RESET} {tool_name}")
                    observation = self.tools.execute_tool(tool_name, args)
                    self.tool_usage[tool_name] = self.tool_usage.get(tool_name, 0) + 1
                    observations.append(f"Résultat de {tool_name}: {observation}")
                    context += f"\nObservation de {tool_name}: {observation}"
                # Re-générer la réponse finale après exécution du plan
                response = await self.model.generate_response(context, self.system_prompt)
                # On continue pour traiter la réponse (qui peut être finale ou un autre outil)
                tool_call = self._parse_json(response)
                if not tool_call or "tool" not in tool_call:
                    final_response = response
                    break
                else:
                    # On laisse la boucle traiter l'outil simple
                    pass
            
            if tool_call and isinstance(tool_call, dict) and "tool" in tool_call:
                thought = tool_call.get('thought', 'Processing...')
                tool_name = tool_call['tool']
                args = tool_call.get('args', {})
                
                print(f"\n{self.ORANGE}{self.BOLD}ЁЯТн THOUGHT{self.RESET} {self.DIM}┬╗{self.RESET} {thought}")
                print(f"{self.AMBER}{self.BOLD}ЁЯЫа  ACTION{self.RESET}  {self.DIM}┬╗{self.RESET} {tool_name}")
                
                observation = self.tools.execute_tool(tool_name, args)
                self.tool_usage[tool_name] = self.tool_usage.get(tool_name, 0) + 1
                
                if tool_name == 'edit_system_prompt' and 'Success' in observation:
                    self.system_prompt = self._load_system_prompt()
                if tool_name == 'update_config' and 'Success' in observation:
                    self.reload_config()
                
                print(f"{self.GREEN}{self.BOLD}ЁЯСБ  OBSERVE{self.RESET} {self.DIM}┬╗{self.RESET} Task Success")
                
                self.log_chat("VOIDCLAW_THOUGHT", thought)
                self.log_chat("VOIDCLAW_ACTION", f"Tool: {tool_name}")
                self.log_chat("OBSERVATION", observation)
                
                context += f"\nAgent Thought: {thought}\nObservation from {tool_name}: {observation}"
                continue
            else:
                # FINAL ANSWER
                final_response = response
                if source == "AUTO":
                    print(f"\n{self.ORANGE}{self.BOLD}ЁЯУб PROACTIVE BROADCAST{self.RESET} {self.DIM}┬╗{self.RESET} {final_response}")
                else:
                    print(f"\n{self.ORANGE}{self.BOLD}{self.LOGO}   VOIDCLAW{self.RESET} {self.DIM}┬╗{self.RESET} {final_response}")
                
                self.log_chat("VOIDCLAW_RESPONSE", final_response)
                if source != "AUTO":
                    self.history.append({"role": "assistant", "content": final_response})
                break
        
        if final_response is None:
            final_response = "Reasoning limit reached."
        
        # Stocker dans la mémoire un résumé de l'échange
        summary = f"User: {user_input}\nAgent: {final_response}"
        self.memory.add_memory(summary, {"source": source, "session": self.session_id})
        self.profile.add_conversation(summary[:200])  # résumé court
        
        return final_response

    async def process_message_stream(self, user_input):
        print(f"\n{self.AMBER}{self.BOLD}ЁЯСд YOU (WEB){self.RESET} {self.DIM}┬╗{self.RESET} {user_input}")
        self.log_chat("USER (WEB)", user_input)
        self.history.append({"role": "user", "content": user_input})
        context = "\n".join([f"{m['role']}: {m['content']}" for m in self.history[-10:]])
        
        # Récupérer souvenirs
        relevant_memories = self.memory.retrieve(user_input, top_k=3)
        memory_context = ""
        if relevant_memories:
            memory_context = "Souvenirs pertinents :\n" + "\n".join([m['text'] for m in relevant_memories])
        if memory_context:
            context = memory_context + "\n" + context
        
        final_text = ""
        for _ in range(5):
            response = await self.model.generate_response(context, self.system_prompt)
            tool_call = self._parse_json(response)
            
            if tool_call and isinstance(tool_call, dict) and "plan" in tool_call:
                plan = tool_call["plan"]
                observations = []
                for step in plan:
                    tool_name = step.get("tool")
                    args = step.get("args", {})
                    if not tool_name:
                        continue
                    yield f"THOUGHT:Exécution du plan - {tool_name}"
                    observation = self.tools.execute_tool(tool_name, args)
                    self.tool_usage[tool_name] = self.tool_usage.get(tool_name, 0) + 1
                    observations.append(f"Résultat de {tool_name}: {observation}")
                    context += f"\nObservation de {tool_name}: {observation}"
                response = await self.model.generate_response(context, self.system_prompt)
                tool_call = self._parse_json(response)
                if not tool_call or "tool" not in tool_call:
                    final_text = response
                    break
                # sinon continue pour traiter outil simple
            
            if tool_call and isinstance(tool_call, dict) and "tool" in tool_call:
                thought = tool_call.get('thought', 'Thinking...')
                tool_name = tool_call['tool']
                args = tool_call.get('args', {})
                
                print(f"\n{self.ORANGE}{self.BOLD}ЁЯТн THOUGHT (WEB){self.RESET} {self.DIM}┬╗{self.RESET} {thought}")
                print(f"{self.AMBER}{self.BOLD}ЁЯЫа  ACTION (WEB){self.RESET}  {self.DIM}┬╗{self.RESET} {tool_name}")
                
                yield f"THOUGHT:{thought} | Executing {tool_name}..."
                observation = self.tools.execute_tool(tool_name, args)
                print(f"{self.GREEN}{self.BOLD}ЁЯСБ  OBSERVE (WEB){self.RESET} {self.DIM}┬╗{self.RESET} Task Success")
                
                self.log_chat("VOIDCLAW_THOUGHT", thought)
                self.log_chat("VOIDCLAW_ACTION", f"Tool: {tool_name}")
                self.log_chat("OBSERVATION", observation)
                
                context += f"\nAgent Thought: {thought}\nObservation: {observation}"
                continue
            else:
                print(f"\n{self.ORANGE}{self.BOLD}{self.LOGO}   VOIDCLAW (WEB){self.RESET} {self.DIM}┬╗{self.RESET} Streaming response...")
                yield "START_STREAM"
                async for chunk in self.model.generate_stream(context, self.system_prompt):
                    if self.interrupted:
                        yield f"CHUNK:\n\n[TRANSMISSION INTERRUPTED BY USER]"
                        self.interrupted = False
                        break
                    final_text += chunk
                    yield f"CHUNK:{chunk}"
                self.log_chat("VOIDCLAW_RESPONSE", final_text)
                self.history.append({"role": "assistant", "content": final_text})
                # Stocker dans la mémoire
                summary = f"User: {user_input}\nAgent: {final_text}"
                self.memory.add_memory(summary, {"source": "WEB", "session": self.session_id})
                self.profile.add_conversation(summary[:200])
                break

def print_dashboard(config):
    ORANGE, GREEN, AMBER, SLATE, RESET, BOLD = '\033[38;5;214m', '\033[92m', '\033[93m', '\033[90m', '\033[0m', '\033[1m'
    logo = r"""
      тЦИтЦИтХЧ   тЦИтЦИтХЧ тЦИтЦИтЦИтЦИтЦИтЦИтХЧ тЦИтЦИтХЧтЦИтЦИтЦИтЦИтЦИтЦИтХЧ  тЦИтЦИтЦИтЦИтЦИтЦИтХЧтЦИтЦИтХЧ      тЦИтЦИтЦИтЦИтЦИтХЧ тЦИтЦИтХЧ    тЦИтЦИтХЧ
      тЦИтЦИтХС   тЦИтЦИтХСтЦИтЦИтХФтХРтХРтХРтЦИтЦИтХЧтЦИтЦИтХСтЦИтЦИтХФтХРтХРтЦИтЦИтХЧтЦИтЦИтХФтХРтХРтХРтХРтХЭтЦИтЦИтХС     тЦИтЦИтХФтХРтХРтЦИтЦИтХЧтЦИтЦИтХС    тЦИтЦИтХС
      тЦИтЦИтХС   тЦИтЦИтХСтЦИтЦИтХС   тЦИтЦИтХСтЦИтЦИтХСтЦИтЦИтХС  тЦИтЦИтХСтЦИтЦИтХС     тЦИтЦИтХС     тЦИтЦИтЦИтЦИтЦИтЦИтЦИтХСтЦИтЦИтХС тЦИтХЧ тЦИтЦИтХС
      тХЪтЦИтЦИтХЧ тЦИтЦИтХФтХЭтЦИтЦИтХС   тЦИтЦИтХСтЦИтЦИтХСтЦИтЦИтХС  тЦИтЦИтХСтЦИтЦИтХС     тЦИтЦИтХС     тЦИтЦИтХФтХРтХРтЦИтЦИтХСтЦИтЦИтХСтЦИтЦИтЦИтХЧтЦИтЦИтХС
       тХЪтЦИтЦИтЦИтЦИтХФтХЭ тХЪтЦИтЦИтЦИтЦИтЦИтЦИтХФтХЭтЦИтЦИтХСтЦИтЦИтЦИтЦИтЦИтЦИтХФтХЭтХЪтЦИтЦИтЦИтЦИтЦИтЦИтХЧтЦИтЦИтЦИтЦИтЦИтЦИтЦИтХЧтЦИтЦИтХС  тЦИтЦИтХСтХЪтЦИтЦИтЦИтХФтЦИтЦИтЦИтХФтХЭ
        тХЪтХРтХРтХРтХЭ   тХЪтХРтХРтХРтХРтХРтХЭ тХЪтХРтХЭтХЪтХРтХРтХРтХРтХРтХЭ  тХЪтХРтХРтХРтХРтХРтХЭтХЪтХРтХРтХРтХРтХРтХРтХЭтХЪтХРтХЭ  тХЪтХРтХЭ тХЪтХРтХРтХЭтХЪтХРтХРтХЭ

           A U T O N O M O U S   C O M M A N D   C E N T E R
    """
    print(f"{ORANGE}тФБ"*64)
    print(f"{ORANGE}{logo}{RESET}")
    print(f"{AMBER}           AI Agent for Windows, Mac, Android & Linux{RESET}")
    print(f"{ORANGE}тФБ"*64 + RESET)
    print(f"{ORANGE}{BOLD}ЁТЖЩ   VoidClaw Hybrid Interface v2.0 (HERMES Edition){RESET}")
    print(f"{AMBER}PROVIDER: {RESET}{config['default_provider'].upper()} | {AMBER}MODEL: {RESET}{config[config['default_provider']]['model']}")
    print(f"{AMBER}CHANNELS: {GREEN}TERMINAL{RESET} & {GREEN}TELEGRAM{RESET} & {GREEN}WEB UI{RESET}")
    print(f"{ORANGE}{'тФБ'*64}{RESET}\n")

async def terminal_loop(agent):
    loop = asyncio.get_running_loop()
    while True:
        try:
            print(f"\033[38;5;214m\033[1mтЭп\033[0m ", end="", flush=True)
            user_input = await loop.run_in_executor(None, sys.stdin.readline)
            if not user_input: break
            user_input = user_input.strip()
            
            if user_input.lower() in ['exit', 'quit']:
                print("\033[91mShutting down VoidClaw...\033[0m")
                os._exit(0)
            if user_input.lower() == 'new chat':
                print(f"\033[92m{agent.clear_session()}\033[0m")
                continue
            if not user_input:
                continue
            
            await agent.process_message(user_input, source="TERM")
        except Exception as e:
            print(f"Terminal Error: {e}")
            break

async def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, 'common', 'config.yaml')
    
    if not os.path.exists(config_path):
        print("\033[91m[!] Configuration file not found at common/config.yaml\033[0m")
        print("\033[93m[*] Please run the installation script first to configure the agent.\033[0m")
        return

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    agent = VoidClawAgent(config_path)
    
    if os.path.exists('/data/data/com.termux'):
        agent.tools._provision_shizuku()
        
    os.system('cls' if os.name == 'nt' else 'clear')
    print_dashboard(config)

    web_thread = threading.Thread(target=start_web_server, args=(agent,), daemon=True)
    web_thread.start()

    print(f"\033[38;5;214m[SYSTEM]\033[0m Starting Autonomous Scheduler...")
    agent.scheduler.start()

    token = config.get('telegram_token', '').strip()
    if token and token != "YOUR_TELEGRAM_BOT_TOKEN":
        print(f"\033[38;5;214m[SYSTEM]\033[0m Establishing Telegram Secure Link...")
        
        async def handle_tg(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not update.message or not update.message.text: return
            agent.last_tg_chat_id = update.effective_chat.id
            print(f"\n\033[38;5;214m[TELEGRAM]\033[0m Incoming transmission from {update.effective_user.first_name}...")
            reply = await agent.process_message(update.message.text, source="TG")
            
            if reply.startswith("SEND_FILE:"):
                file_path = reply.split(":", 1)[1].strip()
                if os.path.exists(file_path):
                    try:
                        with open(file_path, 'rb') as f:
                            await update.message.reply_document(document=f, filename=os.path.basename(file_path))
                    except Exception as e:
                        await update.message.reply_text(f"❌ Erreur lors de l'envoi du fichier : {str(e)}")
                else:
                    await update.message.reply_text(f"❌ Fichier introuvable : `{file_path}`")
            else:
                await update.message.reply_text(reply)

        async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not update.message.document:
                return
            doc = update.message.document
            file = await doc.get_file()
            from werkzeug.utils import secure_filename
            safe_name = secure_filename(doc.file_name) if doc.file_name else f"file_{uuid.uuid4().hex[:8]}"
            file_path = os.path.join(agent.workspace_dir, safe_name)
            await file.download_to_drive(file_path)
            await update.message.reply_text(f"📎 Fichier reçu : `{safe_name}` (sauvegardé dans le workspace)")
            # Notifier l'agent
            await agent.process_message(f"L'utilisateur a envoyé le fichier {safe_name}", source="TG")

        for attempt in range(3):
            try:
                from telegram.request import HTTPXRequest
                request = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0)
                application = ApplicationBuilder().token(token).request(request).build()
                agent.tg_app = application
                
                application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_tg))
                application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
                
                await application.initialize()
                await application.start()
                await application.updater.start_polling(drop_pending_updates=True)
                
                print(f"\033[92m[+] Telegram Bot active.\033[0m")
                await terminal_loop(agent)
                return
            except Exception as e:
                try:
                    if 'application' in locals():
                        await application.shutdown()
                except: pass
                
                if attempt < 2:
                    wait = (attempt + 1) * 5
                    print(f"\033[93m[!] Telegram Connection retry {attempt+1}/3 in {wait}s... ({e})\033[0m")
                    await asyncio.sleep(wait)
                else:
                    print(f"\n\033[91m[!] Telegram Setup Failed: {e}\033[0m")
                    print("\033[93m[*] Continuing in Terminal + Web mode.\033[0m")
                    await terminal_loop(agent)
    else:
        print("\033[93m[!] Telegram token not set. Running in Terminal + Web mode.\033[0m")
        await terminal_loop(agent)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass