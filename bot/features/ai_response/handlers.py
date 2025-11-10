"""AI-powered response handler for Telegram groups."""

import logging
import os
from typing import Optional, Union, List, Dict, Any
import asyncio
from functools import lru_cache
import base64
from io import BytesIO

from telegram import Update, Message, PhotoSize
from telegram.ext import Application, ContextTypes, MessageHandler, filters
from telegram.constants import ChatAction, ParseMode
import openai
import re
from openai import AsyncOpenAI

from ...core.i18n import I18N, t
from ...core.permissions import require_group_admin
from ...core.config import settings
from ...infra import db
from ...infra.settings_repo import SettingsRepo

log = logging.getLogger(__name__)

async def notify_admin_ai_error(context, error_type: str, error_details: str, chat_id: int = None, user_id: int = None):
    """Send AI error notifications to bot admins."""
    try:
        error_message = f"🤖 <b>AI Response Error</b>\n\n"
        error_message += f"<b>Type:</b> {error_type}\n"
        
        if chat_id:
            error_message += f"<b>Chat ID:</b> <code>{chat_id}</code>\n"
        if user_id:
            error_message += f"<b>User ID:</b> <code>{user_id}</code>\n"
        
        error_message += f"\n<b>Details:</b>\n<code>{error_details[:500]}</code>"
        
        # Send to all admins
        for admin_id in settings.OWNER_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=error_message,
                    parse_mode="HTML",
                    disable_notification=True,
                )
            except Exception:
                pass  # Silently fail if can't notify admin
    except Exception:
        pass  # Don't let notification errors break the main flow


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for MarkdownV2 format."""
    # Characters that need to be escaped in MarkdownV2
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    
    # Escape each special character
    for char in escape_chars:
        text = text.replace(char, '\\' + char)
    
    return text

def format_markdown_v2(text: str) -> str:
    """Format AI response text for MarkdownV2.
    
    Converts common markdown patterns to MarkdownV2 format:
    - **bold** -> *bold*
    - *italic* or _italic_ -> _italic_
    - `code` -> `code`
    - ```code block``` -> ```code block```
    - [link](url) -> [link](url)
    - Headers (# text) -> *text*
    - Bullet points preserved
    """
    
    # First, preserve code blocks and inline code
    code_blocks = []
    code_pattern = r'```[\s\S]*?```'
    
    def save_code_block(match):
        code_blocks.append(match.group(0))
        return f'__CODE_BLOCK_{len(code_blocks)-1}__'
    
    text = re.sub(code_pattern, save_code_block, text)
    
    # Save inline code
    inline_codes = []
    inline_pattern = r'`[^`]+`'
    
    def save_inline_code(match):
        inline_codes.append(match.group(0))
        return f'__INLINE_CODE_{len(inline_codes)-1}__'
    
    text = re.sub(inline_pattern, save_inline_code, text)
    
    # Save URLs
    urls = []
    url_pattern = r'\[([^\]]+)\]\(([^\)]+)\)'
    
    def save_url(match):
        urls.append(match.group(0))
        return f'__URL_{len(urls)-1}__'
    
    text = re.sub(url_pattern, save_url, text)
    
    # Now escape special characters
    text = escape_markdown_v2(text)
    
    # Convert headers to bold
    text = re.sub(r'^#+\s*(.+)$', r'*\1*', text, flags=re.MULTILINE)
    
    # Convert **bold** to *bold* (unescape the asterisks)
    text = re.sub(r'\\\*\\\*([^*]+)\\\*\\\*', r'*\1*', text)
    
    # Convert _italic_ or *italic* to _italic_ 
    text = re.sub(r'\\_([^_]+)\\_', r'_\1_', text)
    
    # Handle bullet points - unescape them
    text = re.sub(r'^\\-\s', r'• ', text, flags=re.MULTILINE)
    text = re.sub(r'^\\\*\s', r'• ', text, flags=re.MULTILINE)
    text = re.sub(r'^\\\+\s', r'• ', text, flags=re.MULTILINE)
    
    # Handle numbered lists - unescape the period
    text = re.sub(r'^(\d+)\\\.\s', r'\1\. ', text, flags=re.MULTILINE)
    
    # Restore URLs
    for i, url in enumerate(urls):
        # URLs don't need escaping inside brackets and parentheses
        text = text.replace(f'__URL_{i}__', url)
    
    # Restore inline code
    for i, code in enumerate(inline_codes):
        text = text.replace(f'__INLINE_CODE_{i}__', code)
    
    # Restore code blocks
    for i, block in enumerate(code_blocks):
        text = text.replace(f'__CODE_BLOCK_{i}__', block)
    
    return text

# Initialize OpenAI client (will be configured on first use)
_client: Optional[AsyncOpenAI] = None

def get_openai_client() -> AsyncOpenAI:
    """Get or create OpenAI client instance using latest API."""
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set in environment variables")
        # Initialize with explicit API key as per latest docs
        _client = AsyncOpenAI(
            api_key=api_key,
            # Optional: Add custom headers or organization if needed
            # organization="org-...",
            # default_headers={"OpenAI-Beta": "assistants=v2"}
        )
    return _client

async def is_ai_enabled(chat_id: int) -> bool:
    """Check if AI responses are enabled for this group."""
    async with db.SessionLocal() as s:  # type: ignore
        settings = await SettingsRepo(s).get(chat_id, "ai_response") or {}
        return settings.get("enabled", False)

async def get_ai_settings(chat_id: int) -> dict:
    """Get AI response settings for a group."""
    async with db.SessionLocal() as s:  # type: ignore
        settings = await SettingsRepo(s).get(chat_id, "ai_response") or {
            "enabled": False,
            "model": "gpt-5-mini-2025-08-07",  # Default model - GPT-5 Mini
            "max_tokens": 800,  # Optimized for concise Telegram messages
            "temperature": 1.0,  # GPT-5 requires 1.0
            "system_prompt": None,  # Custom system prompt if set
            "reply_only": True,  # Only respond to replies to bot messages
            "trigger_words": [],  # Optional trigger words to activate AI
        }
        return settings

async def set_ai_enabled(chat_id: int, enabled: bool) -> None:
    """Enable or disable AI responses for a group."""
    async with db.SessionLocal() as s:  # type: ignore
        settings = await SettingsRepo(s).get(chat_id, "ai_response") or {}
        settings["enabled"] = enabled
        await SettingsRepo(s).set(chat_id, "ai_response", settings)
        await s.commit()

async def update_ai_settings(chat_id: int, **kwargs) -> None:
    """Update AI response settings for a group."""
    async with db.SessionLocal() as s:  # type: ignore
        settings = await SettingsRepo(s).get(chat_id, "ai_response") or {}
        settings.update(kwargs)
        await SettingsRepo(s).set(chat_id, "ai_response", settings)
        await s.commit()

def should_respond_to_message(
    message: Message,
    settings: dict,
    bot_username: str,
    bot_id: Optional[int] = None,
) -> bool:
    """Determine if the bot should respond to this message."""
    if not message:
        return False
    
    # Get text from either message.text or message.caption (for media)
    text = None
    if message.text:
        text = message.text.strip()
    elif message.caption:
        text = message.caption.strip()
    
    # No text/caption found
    if not text:
        return False
    
    reply_only = bool(settings.get("reply_only", True))
    configured_triggers = settings.get("trigger_words") or []
    triggers = [w.strip().lower() for w in configured_triggers if isinstance(w, str) and w.strip()]
    if not triggers:
        triggers = ["answer", "جاوب"]

    text_lower = text.lower()

    def _matches_trigger(value: str, trigger: str, loose: bool) -> bool:
        trigger_lower = trigger.lower()
        if value == trigger_lower:
            return True
        if not loose:
            return False
        pattern = rf"(^|\W){re.escape(trigger_lower)}(\W|$)"
        return re.search(pattern, value) is not None

    if message.from_user and bot_id is not None and message.from_user.id == bot_id:
        return False

    if not message.reply_to_message:
        return False

    target = message.reply_to_message.from_user
    if reply_only:
        target_is_bot = False
        if target:
            if bot_id is not None and target.id == bot_id:
                target_is_bot = True
            elif bot_username and target.username and target.username.lower() == bot_username.lower():
                target_is_bot = True
        if not target_is_bot:
            return False
        trigger_matched = any(_matches_trigger(text_lower, trig, loose=False) for trig in triggers)
    else:
        trigger_matched = any(_matches_trigger(text_lower, trig, loose=True) for trig in triggers)

    if not trigger_matched:
        return False

    replied_msg = message.reply_to_message
    if not replied_msg.text and not replied_msg.caption and not replied_msg.photo:
        if not (
            replied_msg.video
            or replied_msg.document
            or replied_msg.voice
            or replied_msg.audio
            or replied_msg.sticker
        ):
            return False

    return True

async def download_and_encode_image(photo: PhotoSize, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    """Download a photo from Telegram and encode it as base64."""
    try:
        # Download the photo file
        file = await context.bot.get_file(photo.file_id)
        file_bytes = BytesIO()
        await file.download_to_memory(file_bytes)
        
        # Encode to base64
        file_bytes.seek(0)
        base64_image = base64.b64encode(file_bytes.read()).decode('utf-8')
        return base64_image
    except Exception as e:
        log.error(f"Error downloading/encoding image: {e}")
        return None

async def generate_ai_response(
    message_content: Union[str, Dict[str, Any]], 
    context_messages: list, 
    settings: dict,
    image_data: Optional[str] = None,
    context: Optional[ContextTypes.DEFAULT_TYPE] = None,
    chat_id: Optional[int] = None,
    user_id: Optional[int] = None
) -> str:
    """Generate AI response using OpenAI API with optional image analysis."""
    try:
        client = get_openai_client()
        
        # Build messages for the API
        messages = []
        
        # Add system prompt
        system_prompt = settings.get("system_prompt") or (
            "You are an expert software engineer responding in a Telegram group chat. "
            "Write like you're messaging a colleague - direct, helpful, technically precise.\n\n"
            
            "RESPONSE STYLE:\n"
            "• Keep responses SHORT (200-400 words typical, 800 max for complex topics)\n"
            "• Start with the answer/solution immediately\n" 
            "• Use the same language as the question (Arabic/English)\n"
            "• Write like a Telegram message, not an article\n"
            "• Be confident and authoritative - you're the expert\n\n"
            
            "FORMATTING:\n"
            "• **Bold** for key points or commands\n"
            "• `code` for inline code\n"
            "• ```language\\ncode``` for code blocks\n"
            "• Use → for steps or consequences\n"
            "• Keep paragraphs SHORT (2-3 sentences max)\n\n"
            
            "RESPONSE STRUCTURE:\n"
            "For questions → Direct answer first, then brief explanation if needed\n"
            "For errors → Issue identified → Quick fix → Command/code\n"
            "For code review → Main issue → Fixed version → Why it matters\n"
            "For images → What I see → The problem → Solution\n"
            "For how-to → Steps 1-2-3 with commands\n\n"
            
            "EXAMPLES:\n"
            "Q: 'Why is my API returning 404?'\n"
            "A: 'Your endpoint path doesn't match. You have `/api/user` but calling `/api/users`.\n\n"
            "Fix: `app.get('/api/users', ...)` or update your request.'\n\n"
            
            "Q: 'How to center a div?'\n"
            "A: 'Use flexbox:\n"
            "```css\\n"
            ".parent {\\n"
            "  display: flex;\\n"
            "  justify-content: center;\\n"
            "  align-items: center;\\n"
            "}\\n```'\n\n"
            
            "IMPORTANT:\n"
            "• NO fluff, greetings, or 'I hope this helps'\n"
            "• NO over-explaining obvious things\n"
            "• If uncertain, say 'Likely X, but check Y'\n"
            "• For Arabic: Use professional technical Arabic\n"
            "• Think Telegram message, not documentation"
        )
        messages.append({"role": "system", "content": system_prompt})
        
        # Add context messages (conversation history)
        for ctx_msg in context_messages:
            role = "assistant" if ctx_msg.get("is_bot") else "user"
            content = ctx_msg.get("content")
            if not content:
                # Fallback to text field for backward compatibility
                content = ctx_msg.get("text", "")
            if content:  # Only add non-empty messages
                # For now, only include text content in context to avoid API errors
                # Images in context would require proper formatting
                if isinstance(content, str):
                    messages.append({"role": role, "content": content})
                elif isinstance(content, list):
                    # Extract text from multimodal content for context
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                    combined_text = " ".join(text_parts).strip()
                    if combined_text:
                        messages.append({"role": role, "content": combined_text})
        
        # Build the current message content
        if image_data:
            # For messages with images, create multimodal content
            user_content = []
            
            # Add text description if provided
            if isinstance(message_content, str) and message_content:
                user_content.append({
                    "type": "text",
                    "text": message_content
                })
            
            # Add the image
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_data}"
                }
            })
            
            messages.append({"role": "user", "content": user_content})
            pass  # Image with text
        else:
            # Text-only message
            messages.append({"role": "user", "content": message_content})
            pass  # Text only
        
        # Generate response using GPT-5 Mini
        # Use max_completion_tokens for GPT-5 models, max_tokens for others
        model_name = settings.get("model", "gpt-5-mini-2025-08-07")
        completion_params = {
            "model": model_name,
            "messages": messages,
        }
        
        # GPT-5 models have different parameter requirements
        if "gpt-5" in model_name:
            # GPT-5 only supports temperature=1.0 (default)
            completion_params["temperature"] = 1.0
            # GPT-5 uses max_completion_tokens instead of max_tokens
            # This includes BOTH reasoning tokens AND output tokens
            # Set higher to ensure we get actual output after reasoning
            completion_params["max_completion_tokens"] = settings.get("max_tokens", 2000)
            # Add reasoning_effort to control reasoning vs output balance
            completion_params["reasoning_effort"] = "minimal"  # Use minimal reasoning for faster responses
            # GPT-5 doesn't support presence_penalty or frequency_penalty
        else:
            # Other models support variable temperature and penalties
            completion_params["temperature"] = settings.get("temperature", 0.7)
            completion_params["max_tokens"] = settings.get("max_tokens", 500)
            completion_params["presence_penalty"] = 0.1
            completion_params["frequency_penalty"] = 0.1
        
        response = await client.chat.completions.create(**completion_params)

        content = (response.choices[0].message.content or "").strip()
        
        if content:
            return content
        else:
            # Empty response from API
            return "I received an empty response from the AI model. Please try again."
        
    except openai.APIError as e:
        log.error(f"OpenAI API error in AI response: {e}")
        
        # Notify admins of API errors
        if context:
            error_details = str(e)[:500]
            if hasattr(e, 'response') and hasattr(e.response, 'status_code'):
                error_details = f"Status: {e.response.status_code}\n{error_details}"
            await notify_admin_ai_error(context, "OpenAI API Error", error_details, chat_id, user_id)
        
        if "model" in str(e).lower():
            return (
                "Model unavailable. An admin can verify the configured model name "
                "and availability in the AI settings, then try again."
            )
        elif "rate" in str(e).lower():
            return "Rate limit reached. Please try again in a moment."
        elif "token" in str(e).lower() or "context_length" in str(e).lower():
            return "The message is too long. Please try with a shorter message."
        else:
            return "AI service temporarily unavailable. Please try again later."
    
    except Exception as e:
        log.error(f"Error generating AI response: {e}", exc_info=True)
        
        # Notify admins of unexpected errors
        if context:
            await notify_admin_ai_error(context, "Unexpected Error", str(e)[:500], chat_id, user_id)
        
        return "An error occurred while generating the response. The admin has been notified."

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle messages and generate AI responses when appropriate."""
    if not update.effective_message or not update.effective_chat:
        return
    
    # Only work in groups
    if update.effective_chat.type == "private":
        return
    
    chat_id = update.effective_chat.id
    message = update.effective_message
    user_id = message.from_user.id if message.from_user else None
    
    # Check if AI is enabled for this group
    if not await is_ai_enabled(chat_id):
        return
    
    # Get AI settings
    settings = await get_ai_settings(chat_id)
    
    # Get bot username
    bot_username = context.bot.username or ""
    
    # Check if we should respond
    bot_id = getattr(context.bot, "id", None)
    if not should_respond_to_message(message, settings, bot_username, bot_id):
        return
    
    # Delete the trigger message ("answer" or "جاوب") for professionalism
    try:
        await message.delete()
        pass  # Trigger message deleted
    except Exception as e:
        pass  # Could not delete trigger message (no permissions)
    
    # Send typing action
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    # Get conversation history from user_data
    conversation_key = f"ai_context_{chat_id}_{user_id}"
    timestamp_key = f"ai_timestamp_{chat_id}_{user_id}"
    
    # Check if context has expired (30 minutes)
    import time
    current_time = time.time()
    last_interaction = context.user_data.get(timestamp_key, 0)
    
    if current_time - last_interaction > 1800:  # 30 minutes
        # Clear old context if expired
        context.user_data[conversation_key] = []
    
    if conversation_key not in context.user_data:
        context.user_data[conversation_key] = []
    
    conversation_history = context.user_data[conversation_key]
    
    # Update timestamp
    context.user_data[timestamp_key] = current_time
    
    # Build context from conversation history
    context_messages = []
    
    # Add previous conversation context (last 5 exchanges)
    for msg in conversation_history[-10:]:  # Last 5 exchanges (user + bot)
        context_messages.append(msg)
    
    # Extract content from the replied-to message
    replied_msg = message.reply_to_message
    target_message_text = ""
    image_data = None
    
    # Detect if the replied message contains a question
    is_question = False
    # English question indicators
    question_indicators = ['?', 'what', 'why', 'how', 'when', 'where', 'who', 'which', 'can', 'could', 'would', 'should', 'is', 'are', 'do', 'does', 'did']
    # Arabic question indicators
    arabic_question_indicators = ['؟', 'ما', 'لماذا', 'كيف', 'متى', 'أين', 'من', 'هل', 'أي', 'ماذا', 'لما', 'إيش', 'وين', 'شو', 'ليه', 'ليش']
    
    # Check if the replied message has a photo that we should analyze
    if replied_msg.photo:
        # Download and encode the largest photo
        largest_photo = replied_msg.photo[-1]  # Get highest resolution
        image_data = await download_and_encode_image(largest_photo, context)
        
        if image_data:
            # Include caption if present
            if replied_msg.caption:
                target_message_text = f"Analyze this image and its caption: {replied_msg.caption}"
                # Check if caption contains a question
                caption_lower = replied_msg.caption.lower()
                is_question = ('?' in replied_msg.caption or '؟' in replied_msg.caption or 
                              any(caption_lower.startswith(word) for word in question_indicators) or
                              any(word in replied_msg.caption for word in arabic_question_indicators))
            else:
                target_message_text = "Analyze this image in detail and provide comprehensive insights"
            
            pass  # Processing image
        else:
            # Failed to download image, fallback to text description
            target_message_text = "[Photo] " + (replied_msg.caption or "No caption")
    elif replied_msg.text:
        # Plain text message
        target_message_text = replied_msg.text
        # Check if text contains a question
        text_lower = replied_msg.text.lower()
        is_question = ('?' in replied_msg.text or '؟' in replied_msg.text or 
                      any(text_lower.strip().startswith(word) for word in question_indicators) or
                      any(word in replied_msg.text for word in arabic_question_indicators))
        
        # Enhance the prompt if it's a question
        if is_question:
            target_message_text = f"Please provide a comprehensive and professional answer to this question: {replied_msg.text}"
    elif replied_msg.caption:
        # Handle other media with caption
        media_type = ""
        if replied_msg.video:
            media_type = "[Video] "
        elif replied_msg.document:
            media_type = "[Document] "
        elif replied_msg.voice:
            media_type = "[Voice message] "
        elif replied_msg.audio:
            media_type = "[Audio] "
        elif replied_msg.sticker:
            media_type = "[Sticker] "
            if replied_msg.sticker.emoji:
                media_type = f"[Sticker: {replied_msg.sticker.emoji}] "
        
        target_message_text = media_type + (replied_msg.caption or "No caption")
    elif replied_msg.sticker and replied_msg.sticker.emoji:
        # Handle sticker without caption
        target_message_text = f"[Sticker: {replied_msg.sticker.emoji}]"
    else:
        # Fallback for media without text
        if replied_msg.video:
            target_message_text = "[Video without caption]"
        elif replied_msg.document:
            target_message_text = "[Document without caption]"
        elif replied_msg.voice:
            target_message_text = "[Voice message]"
        elif replied_msg.audio:
            target_message_text = "[Audio file]"
        else:
            target_message_text = "[Media message]"
    
    # Generate AI response with optional image data
    response_text = await generate_ai_response(
        target_message_text,
        context_messages,
        settings,
        image_data,
        context,
        chat_id,
        user_id
    )
    
    # Store the interaction in conversation history
    # Store content in a format that can handle both text and multimodal
    if image_data:
        # For image messages, store structured content
        content_parts = []
        if target_message_text:
            content_parts.append({"type": "text", "text": target_message_text})
        content_parts.append({"type": "image", "data": "[Image analyzed]"})
        
        conversation_history.append({
            "content": content_parts,
            "text": target_message_text or "[Image analyzed]",  # Keep text for backward compatibility
            "is_bot": False
        })
    else:
        # For text messages, use backward-compatible format
        conversation_history.append({
            "content": target_message_text,
            "text": target_message_text,  # Keep for backward compatibility
            "is_bot": False
        })
    
    conversation_history.append({
        "content": response_text,
        "text": response_text,  # Keep for backward compatibility  
        "is_bot": True
    })
    
    # Keep only last 20 messages in history to prevent memory overflow
    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]
    
    context.user_data[conversation_key] = conversation_history
    
    # Response generated successfully

    # Send the response - ALWAYS reply to the original message that was replied to
    reply_to_id = message.reply_to_message.message_id
    
    # Telegram has a 4096 character limit for messages
    MAX_MESSAGE_LENGTH = 3900  # Leave buffer for markdown
    
    # Truncate BEFORE formatting to avoid cutting off markdown entities
    truncated_text = response_text
    if len(response_text) > MAX_MESSAGE_LENGTH:
        # Find a good break point (end of sentence/paragraph)
        truncated_text = response_text[:MAX_MESSAGE_LENGTH]
        
        # Try to break at a sentence
        for sep in ['\n\n', '\n', '. ', '، ', '؛ ']:
            last_sep = truncated_text.rfind(sep)
            if last_sep > MAX_MESSAGE_LENGTH - 500:  # Within last 500 chars
                truncated_text = truncated_text[:last_sep + len(sep)]
                break
        
        truncated_text += "\n\n... (Response truncated)"
        log.debug(f"Response truncated from {len(response_text)} to {len(truncated_text)} characters")
    
    # Try different formatting options in order of preference
    send_attempts = [
        (ParseMode.MARKDOWN, truncated_text, "Markdown"),
        (ParseMode.HTML, truncated_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'), "HTML"),
        (None, truncated_text, "Plain text")
    ]
    
    for parse_mode, text_to_send, format_name in send_attempts:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text_to_send,
                parse_mode=parse_mode,
                reply_to_message_id=reply_to_id
            )
            pass  # Message sent successfully
            break
        except Exception as e:
            log.debug(f"Failed to send with {format_name}: {e}")
            if format_name == "Plain text":
                # If even plain text fails, there's a bigger problem
                log.error("Failed to send AI response in any format")
                raise
    
    # Log the interaction
    # AI response completed

# Admin commands
@require_group_admin
async def cmd_ai_enable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable AI responses for this group."""
    if not update.effective_chat or update.effective_chat.type == "private":
        return
    
    chat_id = update.effective_chat.id
    lang = I18N.pick_lang(update)
    
    # Check if API key is configured
    try:
        get_openai_client()
    except ValueError:
        await update.effective_message.reply_text(t(lang, "ai.api_key_missing"))
        return
    
    await set_ai_enabled(chat_id, True)
    await update.effective_message.reply_text(t(lang, "ai.enabled"))
    log.debug(f"AI responses enabled for chat {chat_id}")

@require_group_admin
async def cmd_ai_disable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable AI responses for this group."""
    if not update.effective_chat or update.effective_chat.type == "private":
        return
    
    chat_id = update.effective_chat.id
    lang = I18N.pick_lang(update)
    
    await set_ai_enabled(chat_id, False)
    await update.effective_message.reply_text(t(lang, "ai.disabled"))
    log.debug(f"AI responses disabled for chat {chat_id}")

@require_group_admin
async def cmd_ai_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show AI response settings for this group."""
    if not update.effective_chat or update.effective_chat.type == "private":
        return
    
    chat_id = update.effective_chat.id
    lang = I18N.pick_lang(update)
    
    settings = await get_ai_settings(chat_id)
    
    status = t(lang, "ai.status_enabled") if settings["enabled"] else t(lang, "ai.status_disabled")
    model = settings.get("model", "gpt-4o-mini")
    reply_only = t(lang, "ai.reply_only_yes") if settings.get("reply_only", True) else t(lang, "ai.reply_only_no")
    
    text = t(lang, "ai.settings",
             status=status,
             model=model,
             reply_only=reply_only,
             max_tokens=settings.get("max_tokens", 500),
             temperature=settings.get("temperature", 0.7))
    
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

async def cmd_clear_ai_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear AI conversation context for the user."""
    if not update.effective_chat or not update.effective_user:
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = I18N.pick_lang(update)
    
    # Clear conversation history for this user in this chat
    conversation_key = f"ai_context_{chat_id}_{user_id}"
    if conversation_key in context.user_data:
        context.user_data[conversation_key] = []
        await update.effective_message.reply_text(
            "🔄 Your AI conversation context has been cleared.",
            reply_to_message_id=update.effective_message.message_id
        )
    else:
        await update.effective_message.reply_text(
            "ℹ️ No conversation context to clear.",
            reply_to_message_id=update.effective_message.message_id
        )
    
    log.debug(f"AI context cleared for user {user_id} in chat {chat_id}")

async def cmd_ai_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show AI conversation context status."""
    if not update.effective_chat or not update.effective_user:
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Get conversation history
    conversation_key = f"ai_context_{chat_id}_{user_id}"
    conversation_history = context.user_data.get(conversation_key, [])
    
    history_count = len(conversation_history)
    status_text = (
        f"📊 **AI Context Status**\n\n"
        f"Messages in context: {history_count}/20\n"
        f"Context will be maintained across conversations.\n\n"
        f"Use /clear_ai to reset your conversation history."
    )
    
    await update.effective_message.reply_text(
        status_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_to_message_id=update.effective_message.message_id
    )

def register_handlers(app: Application) -> None:
    """Register AI response handlers."""
    # Message handler for AI responses (handles both text and media with captions)
    # Lower priority so other handlers run first
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.CAPTION) & ~filters.COMMAND & filters.ChatType.GROUPS,
        on_message
    ), group=10)  # Lower priority group
    
    # Command handlers
    from telegram.ext import CommandHandler
    app.add_handler(CommandHandler("clear_ai", cmd_clear_ai_context))
    app.add_handler(CommandHandler("ai_status", cmd_ai_status))
    
    log.debug("AI response handlers registered")
