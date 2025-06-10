import discord
from discord import app_commands
from discord.ext import commands
import ollama
import logging
import os
import glob
import subprocess
import time

logger = logging.getLogger('discord')

class Question(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.model_name = "llama3.2:1b"  # Lightest Llama model for local use
        self.knowledge_base = self._load_knowledge_base()
        self._ensure_ollama_setup()
    
    def _load_knowledge_base(self):
        """Load knowledge base from markdown files in the knowledge_base folder"""
        knowledge_base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'knowledge_base')
        knowledge_content = ""
        
        if not os.path.exists(knowledge_base_dir):
            logger.warning(f"Knowledge base directory not found: {knowledge_base_dir}")
            return "No knowledge base available. Please create markdown files in the knowledge_base folder."
        
        # Get all markdown files in the knowledge base directory
        md_files = glob.glob(os.path.join(knowledge_base_dir, "*.md"))
        
        if not md_files:
            logger.warning("No markdown files found in knowledge_base directory")
            return "No knowledge base files found. Please add .md files to the knowledge_base folder."
        
        # Load and combine all markdown files
        for md_file in sorted(md_files):
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                    filename = os.path.basename(md_file)
                    knowledge_content += f"\n\n# From {filename}:\n{file_content}\n"
            except Exception as e:
                logger.error(f"Error reading {md_file}: {e}")
        
        return knowledge_content if knowledge_content else "Error loading knowledge base files."
    
    def _ensure_ollama_setup(self):
        """Ensure Ollama is running and model is available"""
        try:
            # Use the correct command for the OS
            if os.name == 'nt':
                result = subprocess.run(['where', 'ollama'], capture_output=True, text=True)
            else:
                result = subprocess.run(['which', 'ollama'], capture_output=True, text=True)
            if result.returncode != 0:
                logger.warning("Ollama not found. Please install Ollama manually.")
                return
            
            # Check if Ollama service is running
            try:
                ollama.list()
                logger.info("Ollama service is running")
            except Exception:
                logger.info("Starting Ollama service...")
                # Start Ollama service in background
                subprocess.Popen(['ollama', 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(3)  # Give it time to start
            
            # Check if model exists, pull if not
            models = ollama.list()
            model_exists = any(self.model_name in model['name'] for model in models.get('models', []))
            
            if not model_exists:
                logger.info(f"Pulling {self.model_name} model...")
                ollama.pull(self.model_name)
                logger.info(f"Successfully pulled {self.model_name}")
            else:
                logger.info(f"Model {self.model_name} is available")
                
        except Exception as e:
            logger.error(f"Error setting up Ollama: {e}")
            if os.name == 'nt':
                logger.error("Please install Ollama manually: https://ollama.com/download")
            else:
                logger.error("Please install Ollama manually: curl -fsSL https://ollama.ai/install.sh | sh")

    @app_commands.command(description="Ask questions about bot features or game mechanics")
    async def question(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        logger.info(f"/question by {interaction.user.display_name}: {question}")
        
        try:
            # Prepare the prompt with context
            prompt = f"""You are a helpful assistant for the xRC Ranked Bot Discord server. 
            Use the following knowledge base to answer questions about bot features and game mechanics.
            
            Knowledge Base:
            {self.knowledge_base}
            
            User Question: {question}
            
            Please provide a helpful, concise answer based on the knowledge base. If the question is outside the scope of bot features or game mechanics, politely redirect them to use the appropriate commands or resources."""
            
            # Generate response using Ollama
            response = ollama.chat(
                model=self.model_name,
                messages=[{
                    'role': 'user',
                    'content': prompt
                }]
            )
            
            answer = response['message']['content']
            
            # Create embed for the response
            embed = discord.Embed(
                title="❓ Question Assistant",
                description=answer,
                color=discord.Color.blue()
            )
            embed.set_footer(text="Powered by local LLM")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in question command: {e}")
            error_embed = discord.Embed(
                title="❌ Error",
                description="Sorry, I couldn't process your question. Make sure Ollama is running locally with the llama3.2:1b model installed.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    from config import GUILD_ID
    cog = Question(bot)
    guild = await bot.fetch_guild(GUILD_ID)
    assert guild is not None

    await bot.add_cog(
        cog,
        guilds=[guild]
    )