import re
import os
import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient, events, functions, types
from telethon.tl.custom import Button
from telethon.tl.types import User, MessageMediaPhoto, MessageMediaDocument
from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_ID
from database import db

# Настройка логирования
logger = logging.getLogger('notification_bot')

class NotificationBot:
    def __init__(self):
        # Create sessions directory if it doesn't exist
        os.makedirs('sessions', exist_ok=True)
        
        self.bot = TelegramClient('sessions/notification_bot', API_ID, API_HASH)
        self.bot.parse_mode = 'html'
        self.is_running = False
        self.search_mode = False
        
    async def start(self):
        """Запуск бота."""
        if self.is_running:
            logger.warning("Бот уведомлений уже запущен")
            return False
        
        try:
            # Подключение к боту
            await self.bot.start(bot_token=BOT_TOKEN)
            self.is_running = True
            
            # Регистрируем обработчики команд
            self.register_command_handlers()
            
            logger.info("Бот уведомлений запущен")
            return True
        except Exception as e:
            logger.error(f"Ошибка запуска бота уведомлений: {str(e)}")
            self.is_running = False
            return False
    
    def register_command_handlers(self):
        """Регистрация обработчиков команд бота."""
        try:
            # Обработчик команды /start
            @self.bot.on(events.NewMessage(pattern='/start'))
            async def start_command(event):
                if event.chat_id != ADMIN_ID:
                    return  # Игнорируем команды не от админа
                
                await event.respond("👋 Привет! Я бот для уведомлений о новых сообщениях.\n\n"
                                   "Команды:\n"
                                   "/start - Показать это сообщение\n"
                                   "/поиск - Поиск пользователя по имени/юзернейму")
            
            # Обработчик команды /поиск
            @self.bot.on(events.NewMessage(pattern='/поиск'))
            async def search_command(event):
                if event.chat_id != ADMIN_ID:
                    return  # Игнорируем команды не от админа
                
                # Переводим бота в режим поиска
                self.search_mode = True
                await event.respond("Введите имя пользователя, фамилию или @username для поиска")
            
            # Обработчик всех сообщений от админа
            @self.bot.on(events.NewMessage(from_users=ADMIN_ID))
            async def handle_admin_message(event):
                # Игнорируем команды
                if event.text.startswith('/'):
                    return
                
                # Выполняем поиск, если запрошен
                if self.search_mode:
                    search_query = event.text.strip()
                    
                    # Удаляем @ из начала, если есть
                    if search_query.startswith('@'):
                        search_query = search_query[1:]
                    
                    # Выполняем поиск по базе данных
                    user = db.get_user_by_username(search_query)
                    
                    if user:
                        # Получаем историю сообщений
                        messages = db.get_messages_by_user_id(user['id'])
                        
                        # Формируем информацию о пользователе
                        user_info = f"Найден пользователь 👑\n\n"
                        if user['username']:
                            user_info += f"Username: @{user['username']}\n"
                        if user['first_name'] or user['last_name']:
                            user_info += f"Имя: {user['first_name']} {user['last_name']}\n"
                        if user['phone']:
                            user_info += f"Телефон: {user['phone']}\n"
                        
                        await event.respond(user_info)
                        
                        # Отправляем историю сообщений
                        if messages:
                            history_text = "История сообщений:\n\n"
                            for msg in messages:
                                direction = "➡️" if msg['is_incoming'] else "⬅️"
                                timestamp = msg['timestamp']
                                # Форматируем дату
                                try:
                                    date_obj = datetime.fromisoformat(timestamp)
                                    date_str = date_obj.strftime("%Y-%m-%d %H:%M:%S")
                                except:
                                    date_str = timestamp
                                
                                history_text += f"{direction} {msg['message_text']}\n{date_str}\n\n"
                                
                                # Отправляем частями, если текст слишком длинный
                                if len(history_text) > 3000:
                                    await event.respond(history_text)
                                    history_text = ""
                            
                            if history_text:
                                await event.respond(history_text)
                        else:
                            await event.respond("История сообщений пуста")
                    else:
                        await event.respond(f"Пользователь {search_query} не найден. Попробуйте другое имя или введите /поиск для нового поиска.")
                    
                    # Выходим из режима поиска
                    self.search_mode = False
            
            logger.info("Обработчики команд бота зарегистрированы")
        except Exception as e:
            logger.error(f"Ошибка регистрации обработчиков команд: {str(e)}")
    
    async def stop(self):
        """Остановка бота."""
        if not self.is_running:
            logger.warning("Бот уведомлений не запущен")
            return
            
        try:
            await self.bot.disconnect()
            self.is_running = False
            logger.info("Бот уведомлений остановлен")
        except Exception as e:
            logger.error(f"Ошибка остановки бота уведомлений: {e}")
            
    async def send_notification(self, user_info: User, message_text: str, message_count: int = 1, event=None):
        """Отправка уведомления о новом сообщении администратору."""
        if not self.is_running:
            logger.warning("Бот уведомлений не запущен, уведомление не отправлено")
            return
        
        try:
            # Получаем информацию о пользователе
            username = getattr(user_info, 'username', None)
            user_id = getattr(user_info, 'id', 'неизвестно')
            first_name = getattr(user_info, 'first_name', '')
            last_name = getattr(user_info, 'last_name', '')
            
            # Проверяем, не является ли отправитель самим админом
            if user_id == ADMIN_ID:
                logger.info(f"Пропущено уведомление о сообщении от админа (ID: {ADMIN_ID})")
                return False
            
            # Формируем отображаемое имя пользователя
            display_name = ""
            if username:
                display_name = f"@{username}"
            else:
                # Если нет username, используем имя и фамилию
                if first_name or last_name:
                    display_name = f"{first_name} {last_name}".strip()
                else:
                    # Если вообще нет информации, используем ID
                    display_name = f"user_id:{user_id}"
            
            # Проверяем, является ли сообщение стикером или медиа
            is_media = False
            original_message = None
            media_text = None
            
            # Получаем оригинальное сообщение
            if event and hasattr(event, 'message'):
                original_message = event.message
            elif hasattr(user_info, '_message') and user_info._message:
                original_message = user_info._message
            
            # Определяем тип сообщения, если есть оригинальное сообщение
            if original_message:
                # Проверяем на стикер
                if hasattr(original_message, 'sticker') and original_message.sticker:
                    is_media = True
                    media_text = "📱 [Стикер]"
                
                # Проверяем на различные типы медиа
                elif hasattr(original_message, 'media') and original_message.media:
                    is_media = True
                    media = original_message.media
                    
                    if isinstance(media, MessageMediaPhoto):
                        media_text = "📷 [Фото]"
                    elif isinstance(media, MessageMediaDocument):
                        # Проверяем mime-тип, если доступен
                        if hasattr(media.document, 'mime_type'):
                            mime_type = media.document.mime_type
                            if 'video' in mime_type:
                                media_text = "🎬 [Видео]"
                            elif 'audio' in mime_type:
                                media_text = "🎵 [Аудио]"
                            elif 'image' in mime_type:
                                media_text = "📷 [Изображение]"
                            else:
                                media_text = "📱 [Медиа]"
                        else:
                            media_text = "📱 [Медиа]"
                    else:
                        media_text = "📱 [Медиа]"
                
                # Если это медиа, используем определенный тип для текста сообщения
                if is_media and media_text:
                    message_text = media_text
            
            # ПРОСТАЯ ПРЯМАЯ ПЕРЕСЫЛКА МЕДИА
            media_forwarded = False
            if is_media and original_message and event and hasattr(event, '_client'):
                try:
                    logger.info(f"Пересылаю медиа ({media_text}) напрямую в бота...")
                    
                    # Получаем клиент и ID сообщения
                    client = event._client
                    message_id = original_message.id
                    chat_id = event.chat_id
                    
                    # Получаем ID бота из токена (первая часть до двоеточия)
                    bot_id = int(BOT_TOKEN.split(':')[0])
                    logger.info(f"ID бота для пересылки: {bot_id}")
                    
                    # ПРЯМАЯ ПЕРЕСЫЛКА через forward_messages В БОТА
                    forwarded = await client.forward_messages(
                        entity=bot_id,         # ID бота
                        messages=message_id,   # ID сообщения для пересылки
                        from_peer=chat_id      # ID чата отправителя
                    )
                    
                    if forwarded:
                        logger.info(f"Медиа успешно переслано в бота!")
                        
                        # Теперь пересылаем от бота админу
                        try:
                            await self.bot.forward_messages(
                                entity=ADMIN_ID,         # ID админа
                                messages=forwarded.id,   # ID только что пересланного сообщения
                                from_peer=bot_id         # ID бота (откуда пересылать)
                            )
                            logger.info(f"Медиа успешно переслано от бота админу!")
                            media_forwarded = True
                        except Exception as e2:
                            logger.error(f"Ошибка при пересылке от бота админу: {e2}")
                    else:
                        logger.error(f"Что-то пошло не так при пересылке в бота")
                
                except Exception as e:
                    logger.error(f"Ошибка при пересылке медиа в бота: {e}")
            
            # Отправляем текстовое уведомление только если это не медиа или медиа не удалось переслать
            if not is_media or not media_forwarded:
                # Форматируем уведомление в зависимости от количества сообщений
                if message_count == 1:
                    notification_text = (
                        f"<b>Новое сообщение!</b>👑\n"
                        f"{message_text}🗨️\n\n"
                        f"<b>Контакт:</b> ({display_name})💛"
                    )
                else:
                    notification_text = (
                        f"<b>Сообщение ({message_count})!</b>👑\n"
                        f"{message_text}🗨️\n\n"
                        f"<b>Контакт:</b> ({display_name})💛"
                    )
                
                # Сохраняем сообщение в базе данных
                db.save_message(
                    user_id=user_id,
                    username=username or "",
                    first_name=first_name,
                    last_name=last_name,
                    message_text=message_text,
                    is_incoming=True
                )
                
                # Создаем кнопки для перехода к пользователю
                buttons = []
                
                # Если есть username, добавляем ссылку на t.me/username
                if username:
                    buttons.append(Button.url("Перейти к диалогу 🚀", f"https://t.me/{username}"))
                else:
                    # Для пользователей без username используем tg://user?id
                    if isinstance(user_id, int) or (isinstance(user_id, str) and user_id.isdigit()):
                        buttons.append(Button.url("Перейти к диалогу 🚀", f"tg://user?id={user_id}"))
                
                try:
                    await self.bot.send_message(
                        ADMIN_ID, 
                        notification_text, 
                        buttons=buttons if buttons else None, 
                        parse_mode='html'
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления: {str(e)}")
                    return False
            
            logger.info(f"Сообщение от {display_name} успешно обработано")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка обработки уведомления: {str(e)}")
            return False

# Создаем глобальный экземпляр бота
notification_bot = NotificationBot()
