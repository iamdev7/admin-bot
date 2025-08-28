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
from openai import AsyncOpenAI

from ...core.i18n import I18N, t
from ...core.permissions import require_group_admin
from ...infra import db
from ...infra.settings_repo import SettingsRepo

log = logging.getLogger(__name__)

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
            "max_tokens": 1000,  # Increased for more comprehensive responses
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

def should_respond_to_message(message: Message, settings: dict, bot_username: str) -> bool:
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
    
    # Only trigger if:
    # 1. The message is EXACTLY "answer" or "جاوب" (no other words)
    # 2. The message is a reply to another message
    text_lower = text.lower()
    
    # Check if message is EXACTLY "answer" or "جاوب" (Arabic for "answer")
    if text_lower != "answer" and text != "جاوب":
        return False
    
    # Check if this is a reply to another message
    if not message.reply_to_message:
        return False
    
    # Check if there's content to analyze (text, caption, or photo/media)
    replied_msg = message.reply_to_message
    # Allow text, captions, or photos (even without caption)
    if not replied_msg.text and not replied_msg.caption and not replied_msg.photo:
        # Also check for other media types
        if not (replied_msg.video or replied_msg.document or replied_msg.voice or 
                replied_msg.audio or replied_msg.sticker):
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
    image_data: Optional[str] = None
) -> str:
    """Generate AI response using OpenAI API with optional image analysis."""
    try:
        client = get_openai_client()
        
        # Build messages for the API
        messages = []
        
        # Add system prompt
        system_prompt = settings.get("system_prompt") or (
            "You are a highly professional AI assistant in a Telegram group chat. "
            "Your role is to provide expert-level, accurate, and helpful responses. "
            "\n\nKey Guidelines:\n"
            "1. RESPONSE STYLE:\n"
            "   - Be professional, knowledgeable, and respectful\n"
            "   - Use clear, concise language without unnecessary formality\n"
            "   - Adapt your tone to match the context (technical for tech questions, friendly for casual topics)\n"
            "   - Never use filler phrases or apologize unnecessarily\n"
            "\n2. QUESTION HANDLING:\n"
            "   - If the message contains a question (even implied), provide a direct, informative answer\n"
            "   - For factual questions: Give accurate, verified information\n"
            "   - For opinion questions: Provide balanced, thoughtful perspectives\n"
            "   - For technical questions: Include relevant details and examples when helpful\n"
            "   - If uncertain: Acknowledge limitations but offer the best available information\n"
            "\n3. IMAGE ANALYSIS:\n"
            "   - When analyzing images, be specific and detailed in your observations\n"
            "   - Identify key elements, context, and relevant information\n"
            "   - If the image contains text, transcribe or summarize it\n"
            "   - Provide insights or answer questions related to the visual content\n"
            "\n4. CONTENT UNDERSTANDING:\n"
            "   - Recognize different types of content: questions, statements, requests, images\n"
            "   - For statements: Acknowledge and expand with relevant information if valuable\n"
            "   - For requests: Fulfill them precisely and completely\n"
            "   - Media indicators like [Photo], [Video], etc. should be acknowledged appropriately\n"
            "\n5. CONVERSATION CONTEXT:\n"
            "   - Maintain awareness of previous exchanges in the conversation\n"
            "   - Reference earlier points when relevant\n"
            "   - Build upon previous responses to create coherent dialogue\n"
            "\n6. RESPONSE LENGTH:\n"
            "   - Keep responses concise but complete (typically under 500 characters)\n"
            "   - For complex topics, structure information with bullet points or numbered lists\n"
            "   - Prioritize clarity and value over brevity\n"
            "\nRemember: You are a trusted knowledge resource. Users rely on your expertise and accuracy."
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
        else:
            # Text-only message
            messages.append({"role": "user", "content": message_content})
        
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
            completion_params["max_completion_tokens"] = settings.get("max_tokens", 500)
            # GPT-5 doesn't support presence_penalty or frequency_penalty
        else:
            # Other models support variable temperature and penalties
            completion_params["temperature"] = settings.get("temperature", 0.7)
            completion_params["max_tokens"] = settings.get("max_tokens", 500)
            completion_params["presence_penalty"] = 0.1
            completion_params["frequency_penalty"] = 0.1
        
        response = await client.chat.completions.create(**completion_params)
        
        return response.choices[0].message.content or "I couldn't generate a response."
        
    except openai.APIError as e:
        log.error(f"OpenAI API error: {e}")
        if "model" in str(e).lower():
            return "The configured model is not available. Please check the model settings."
        return "Sorry, I encountered an API error while generating a response."
    except Exception as e:
        log.error(f"Error generating AI response: {e}")
        return "Sorry, I encountered an error while generating a response."

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
    if not should_respond_to_message(message, settings, bot_username):
        return
    
    # Delete the trigger message ("answer" or "جاوب") for professionalism
    try:
        await message.delete()
        log.debug(f"Deleted trigger message from user {user_id} in chat {chat_id}")
    except Exception as e:
        log.debug(f"Could not delete trigger message: {e}")
    
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
            
            log.info(f"Processing image for AI analysis in chat {chat_id}")
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
        image_data
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
    
    # Send the response - ALWAYS reply to the original message that was replied to
    reply_to_id = message.reply_to_message.message_id
    
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=response_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_to_message_id=reply_to_id
        )
    except Exception:
        # If markdown fails, send as plain text
        await context.bot.send_message(
            chat_id=chat_id,
            text=response_text,
            reply_to_message_id=reply_to_id
        )
    
    # Log the interaction
    log.info(f"AI response generated for chat {chat_id}, user {message.from_user.id if message.from_user else 'unknown'}")

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
    log.info(f"AI responses enabled for chat {chat_id}")

@require_group_admin
async def cmd_ai_disable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable AI responses for this group."""
    if not update.effective_chat or update.effective_chat.type == "private":
        return
    
    chat_id = update.effective_chat.id
    lang = I18N.pick_lang(update)
    
    await set_ai_enabled(chat_id, False)
    await update.effective_message.reply_text(t(lang, "ai.disabled"))
    log.info(f"AI responses disabled for chat {chat_id}")

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
    
    log.info(f"AI context cleared for user {user_id} in chat {chat_id}")

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
    
    log.info("AI response handlers registered")