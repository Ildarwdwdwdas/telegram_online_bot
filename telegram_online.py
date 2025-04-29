import argparse
import asyncio
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler

from colorama import Fore, Style, init
from telethon import TelegramClient, events, functions, types, utils

# Импортируем конфигурацию и компоненты
from config import API_ID, API_HASH, ONLINE_UPDATE_INTERVAL, ACCOUNTS_FILE, ADMIN_ID, IGNORED_USERS
from database import db
from notification_bot import notification_bot

# Инициализация colorama
init()

# Создание директории для логов, если её нет
os.makedirs('logs', exist_ok=True)

# Настройка логгера для общих логов
logger = logging.getLogger('telegram_online')
logger.setLevel(logging.INFO)

# Файловый обработчик с ротацией файлов
file_handler = RotatingFileHandler(
    f'logs/telegram_online_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
    maxBytes=10 * 1024 * 1024,  # 10 МБ
    backupCount=5,
    encoding='utf-8'  # Явное указание кодировки UTF-8
)
file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-7s | %(message)s', '%Y-%m-%d %H:%M:%S'))
logger.addHandler(file_handler)

# Консольный обработчик с цветным форматированием
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-7s | %(message)s', '%Y-%m-%d %H:%M:%S'))
logger.addHandler(console_handler)

# Логгер для сообщений
message_logger = logging.getLogger('message_logger')
message_logger.setLevel(logging.INFO)

# Файловый обработчик с ротацией файлов для сообщений
message_file_handler = RotatingFileHandler(
    f'logs/messages_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
    maxBytes=50 * 1024 * 1024,  # Увеличиваем до 50 МБ
    backupCount=10,  # Увеличиваем число файлов для ротации
    encoding='utf-8'  # Явное указание кодировки UTF-8
)
message_file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-7s | %(message)s', '%Y-%m-%d %H:%M:%S'))
message_logger.addHandler(message_file_handler)

class MultiAccountTelegramBot:
    def __init__(self, use_proxy=False):
        self.use_proxy = use_proxy
        self.accounts = self.load_accounts()
        self.clients = {}
        self.is_running = True
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.notification_bot = None  # Инициализируем как None
        
    def load_accounts(self):
        """Загрузка данных аккаунтов из файла"""
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, 'r') as f:
                    accounts = json.load(f)
                    # Проверяем наличие всех необходимых полей
                    for account in accounts:
                        # Добавляем путь к файлу сессии, если его нет
                        if 'session_file' not in account:
                            account['session_file'] = f"sessions/{account['phone']}"
                    return accounts
            except Exception as e:
                logger.error(f"Ошибка загрузки аккаунтов: {e}")
                return []
        return []
    
    def save_accounts(self):
        """Сохранение данных аккаунтов в файл"""
        try:
            with open(ACCOUNTS_FILE, 'w') as f:
                json.dump(self.accounts, f, indent=4)
        except Exception as e:
            logger.error(f"Ошибка сохранения аккаунтов: {e}")

    # Создаем клиента Telegram
    def create_client(self, session_file):
        # Создаем клиента с или без прокси
        if self.use_proxy:
            proxy = {
                'proxy_type': 'socks5',
                'addr': '127.0.0.1',
                'port': 9050,
                'username': '',
                'password': '',
                'rdns': True
            }
            client = TelegramClient(session_file, API_ID, API_HASH, proxy=proxy)
            logger.info(f"{Fore.CYAN}Клиент для {session_file} создан с использованием прокси{Style.RESET_ALL}")
        else:
            client = TelegramClient(session_file, API_ID, API_HASH)
            logger.info(f"{Fore.CYAN}Клиент для {session_file} создан без использования прокси{Style.RESET_ALL}")
        return client

    async def setup_client(self, account_data):
        """Настройка и запуск клиента для одного аккаунта"""
        phone = account_data['phone']
        session_file = account_data['session_file']
        
        # Проверка существования файла сессии
        session_exists = os.path.exists(f"{session_file}.session")
        logger.info(f"{Fore.YELLOW}Файл сессии для {phone} существует: {session_exists}{Style.RESET_ALL}")
        
        # Создаем клиента
        client = self.create_client(session_file)
        
        # Если клиент не был создан, выходим
        if not client:
            logger.error(f"{Fore.RED}[{phone}] Не удалось создать клиента{Style.RESET_ALL}")
            return
        
        # Сохраняем клиента в словаре для возможного доступа извне
        self.clients[phone] = client
        
        try:
            # Запускаем клиента
            await client.connect()
            
            # Если клиент не авторизован, выполняем авторизацию
            if not await client.is_user_authorized():
                result = await self.authenticate_account(client, account_data)
                if not result:
                    logger.error(f"{Fore.RED}[{phone}] Не удалось авторизовать аккаунт{Style.RESET_ALL}")
                    return
            
            # Получаем информацию о пользователе
            me = await client.get_me()
            logger.info(f"{Fore.GREEN}[{phone}] Авторизован как {me.first_name} {me.last_name if me.last_name else ''} (@{me.username if me.username else 'без username'}){Style.RESET_ALL}")
            
            # Загружаем диалоги для кэширования
            await self.cache_dialogs(client, phone)
        except Exception as e:
            logger.error(f"{Fore.RED}[{phone}] Ошибка при подключении клиента: {e}{Style.RESET_ALL}")
            return
        
        logger.info(f"{Fore.GREEN}Клиент для {account_data['phone']} настроен и готов{Style.RESET_ALL}")
        # Отключаем клиента после настройки, он будет подключен снова при запуске
        await client.disconnect()
        return True
    
    async def run_client(self, account_data):
        """Запуск клиента с периодическим обновлением статуса online"""
        client = None
        try:
            # Получаем данные аккаунта
            name = account_data.get('name', 'Неизвестный')
            phone = account_data.get('phone', 'Неизвестный')
            session_file = account_data.get('session_file', f"telegram_session_{len(self.accounts) + 1}")
            
            logger.info(f"{Fore.CYAN}[{phone}] Запуск клиента {name}...{Style.RESET_ALL}")
            
            # Создаем клиента
            client = self.create_client(session_file)
            
            # Если клиент не был создан, выходим
            if not client:
                logger.error(f"{Fore.RED}[{phone}] Не удалось создать клиента{Style.RESET_ALL}")
                return
            
            # Сохраняем клиента в словаре для возможного доступа извне
            self.clients[phone] = client
            
            # Настраиваем обработчик сообщений для этого клиента
            client.add_event_handler(
                lambda event: self.handle_new_message(client, event, phone),
                events.NewMessage
            )
            
            # Запускаем клиента и проверяем авторизацию
            await client.connect()
            
            # Если клиент не авторизован, выполняем авторизацию
            if not await client.is_user_authorized():
                result = await self.authenticate_account(client, account_data)
                if not result:
                    logger.error(f"{Fore.RED}[{phone}] Не удалось авторизовать аккаунт{Style.RESET_ALL}")
                    return
            
            # Получаем информацию о пользователе
            me = await client.get_me()
            logger.info(f"{Fore.GREEN}[{phone}] Авторизован как {me.first_name} {me.last_name if me.last_name else ''} (@{me.username if me.username else 'без username'}){Style.RESET_ALL}")
            
            # Загружаем диалоги для кэширования
            await self.cache_dialogs(client, phone)
            
            # Запускаем цикл обновления статуса онлайн
            while self.is_running:
                try:
                    # Убеждаемся, что клиент существует и подключен
                    if client and client.is_connected():
                        # Обновляем статус онлайн
                        await client(functions.account.UpdateStatusRequest(offline=False))
                        logger.info(f"{Fore.CYAN}[{phone}] Статус онлайн обновлен...{Style.RESET_ALL}")
                    else:
                        logger.warning(f"{Fore.YELLOW}[{phone}] Клиент не подключен, пропускаем обновление статуса{Style.RESET_ALL}")
                        # Попытка переподключения
                        try:
                            await client.connect()
                            logger.info(f"{Fore.GREEN}[{phone}] Клиент переподключен{Style.RESET_ALL}")
                        except Exception as ce:
                            logger.error(f"{Fore.RED}[{phone}] Ошибка переподключения клиента: {ce}{Style.RESET_ALL}")
                        
                    # Ждем некоторое время
                    await asyncio.sleep(ONLINE_UPDATE_INTERVAL)
                except Exception as e:
                    logger.error(f"{Fore.RED}[{phone}] Ошибка обновления статуса: {e}{Style.RESET_ALL}")
                    await asyncio.sleep(5)  # В случае ошибки подождем немного дольше
            
        except Exception as e:
            logger.error(f"{Fore.RED}[{phone}] Критическая ошибка в работе клиента: {e}{Style.RESET_ALL}")
        finally:
            # При выходе из цикла отключаем клиент
            if client:
                try:
                    await client.disconnect()
                    logger.info(f"{Fore.YELLOW}[{phone}] Клиент отключен{Style.RESET_ALL}")
                except Exception as e:
                    logger.error(f"{Fore.RED}[{phone}] Ошибка отключения клиента: {e}{Style.RESET_ALL}")
            
            # Удаляем клиент из словаря
            if 'phone' in locals() and phone in self.clients:
                del self.clients[phone]
    
    async def authenticate_account(self, client, account_data):
        """Аутентификация аккаунта."""
        phone = account_data.get("phone", "Неизвестный")
        
        try:
            # Если сессии нет, запрашиваем номер телефона и код
            logger.info(f"{Fore.YELLOW}Запрашиваем авторизацию для аккаунта {account_data['name']}{Style.RESET_ALL}")
            await client.start(phone=lambda: input(f'{Fore.YELLOW}Введите номер телефона для {account_data["name"]}: {Style.RESET_ALL}'))
            logger.info(f"{Fore.GREEN}Авторизация успешна!{Style.RESET_ALL}")
            
            # Обновляем номер в данных аккаунта
            actual_user = await client.get_me()
            if hasattr(actual_user, 'phone'):
                account_data['phone'] = actual_user.phone
                self.save_accounts()
                logger.info(f"{Fore.GREEN}Номер телефона обновлен: {account_data['phone']}{Style.RESET_ALL}")
            return True
        except Exception as e:
            logger.error(f"{Fore.RED}Ошибка авторизации: {e}{Style.RESET_ALL}")
            return False
    
    async def cache_dialogs(self, client, phone):
        """Загрузка диалогов для кэширования сущностей."""
        try:
            logger.info(f"{Fore.YELLOW}[{phone}] Загрузка диалогов для кэширования...{Style.RESET_ALL}")
            await client(functions.messages.GetDialogsRequest(
                offset_date=None,
                offset_id=0,
                offset_peer=types.InputPeerEmpty(),
                limit=100,
                hash=0
            ))
            logger.info(f"{Fore.GREEN}[{phone}] Диалоги загружены успешно{Style.RESET_ALL}")
            return True
        except Exception as e:
            logger.error(f"{Fore.RED}[{phone}] Ошибка загрузки диалогов: {e}{Style.RESET_ALL}")
            return False
    
    async def handle_new_message(self, client, event, phone):
        """Обработка новых сообщений."""
        try:
            if not event.is_private:
                return  # Игнорируем групповые сообщения
                
            # Получаем информацию о сообщении
            chat = await event.get_chat()
            sender = await event.get_sender()
            
            # Проверяем, является ли отправитель ботом
            if hasattr(sender, 'bot') and sender.bot:
                logger.info(f"{Fore.YELLOW}[{phone}] Сообщение от бота проигнорировано{Style.RESET_ALL}")
                return
                
            # Проверяем, не является ли отправитель админом
            if hasattr(sender, 'id') and sender.id == ADMIN_ID:
                logger.info(f"{Fore.YELLOW}[{phone}] Сообщение от админа проигнорировано{Style.RESET_ALL}")
                return

            # Проверяем, не находится ли отправитель в списке игнорируемых
            if hasattr(sender, 'id') and sender.id in IGNORED_USERS:
                logger.info(f"{Fore.YELLOW}[{phone}] Сообщение от игнорируемого пользователя {sender.id} проигнорировано{Style.RESET_ALL}")
                return
                
            # Получаем чат и информацию об отправителе
            chat_id = chat.id
            user_id = sender.id
            user_first_name = getattr(sender, 'first_name', '')
            user_last_name = getattr(sender, 'last_name', '')
            username = getattr(sender, 'username', None)
            
            # Получаем текст сообщения и информацию о медиа
            message_text = event.message.message or ""
            media_type = None
            
            # Определяем тип медиа
            if event.media:
                if isinstance(event.media, types.MessageMediaPhoto):
                    media_type = "📷 [Фото]"
                elif isinstance(event.media, types.MessageMediaDocument):
                    # Проверяем, является ли документ стикером
                    if event.message.sticker:
                        media_type = "📱 [Стикер]"
                    # Проверяем mime-тип для определения типа медиа
                    elif hasattr(event.media.document, 'mime_type'):
                        mime_type = event.media.document.mime_type
                        if 'video' in mime_type:
                            media_type = "🎬 [Видео]"
                        elif 'audio' in mime_type:
                            media_type = "🎵 [Аудио]"
                        elif 'image' in mime_type:
                            media_type = "📷 [Изображение]"
                        else:
                            media_type = "📎 [Документ]"
                    else:
                        media_type = "📎 [Документ]"
                else:
                    media_type = "📱 [Медиа]"
                        
            # Формируем строку для логирования
            user_display = f"@{username}" if username else f"{user_first_name} {user_last_name}".strip()
            log_message = f"{Fore.CYAN}[{phone}] Новое сообщение от {user_display}: {message_text}"
            if media_type:
                log_message += f" {media_type}"
            log_message += Style.RESET_ALL
            
            # Логируем сообщение
            message_logger.info(log_message)
            
            # Отметка сообщения как прочитанного
            try:
                # Метод 1: Стандартный API
                try:
                    await client.send_read_acknowledge(chat_id)
                    message_logger.info(f"{Fore.GREEN}[{phone}] Сообщение от {username if username else user_display} отмечено как прочитанное{Style.RESET_ALL}")
                except Exception as e:
                    # Если не сработал стандартный метод, пробуем альтернативы
                    logger.error(f"{Fore.YELLOW}[{phone}] Метод 1 не удался: {str(e)}{Style.RESET_ALL}")
                    
                    # Метод 2: Через сырой API запрос
                    try:
                        # Используем более низкоуровневый метод
                        result = await client(functions.messages.ReadHistoryRequest(
                            peer=chat_id,
                            max_id=event.message.id
                        ))
                        message_logger.info(f"{Fore.GREEN}[{phone}] Сообщение от {username if username else user_display} отмечено как прочитанное (метод 2){Style.RESET_ALL}")
                    except Exception as e:
                        logger.error(f"{Fore.RED}[{phone}] Не удалось отметить сообщение как прочитанное: {str(e)}{Style.RESET_ALL}")
            except Exception as e:
                logger.error(f"{Fore.RED}[{phone}] Общая ошибка отметки сообщения: {str(e)}{Style.RESET_ALL}")
            
            # Теперь ВСЕ сообщения (и текстовые, и медиа) отправляются ТОЛЬКО через бота
            if hasattr(self, 'notification_bot') and self.notification_bot:
                try:
                    # Убедимся, что событие имеет доступ к клиенту для пересылки
                    # Записываем клиент в атрибут события для пересылки медиа
                    if not hasattr(event, 'client'):
                        event._client = client
                        
                    # Подготовка текста сообщения
                    notification_text = message_text
                    
                    logger.info(f"{Fore.YELLOW}[{phone}] Отправляю сообщение через бота...{Style.RESET_ALL}")
                    
                    # Отправка сообщения через бота
                    asyncio.create_task(
                        self.notification_bot.send_notification(sender, notification_text, event=event)
                    )
                except Exception as e:
                    logger.error(f"{Fore.RED}[{phone}] Ошибка отправки сообщения через бота: {str(e)}{Style.RESET_ALL}")
            else:
                logger.warning(f"{Fore.YELLOW}[{phone}] Бот уведомлений не запущен, сообщение не отправлено{Style.RESET_ALL}")
            
            logger.info(f"{Fore.GREEN}[{phone}] Сообщение обработано{Style.RESET_ALL}")
                
        except Exception as e:
            logger.error(f"{Fore.RED}[{phone}] Ошибка обработки сообщения: {str(e)[:100]}{Style.RESET_ALL}")
    
    async def start_all_clients(self):
        """Запуск всех клиентов"""
        # Запускаем бота для уведомлений
        try:
            # Запускаем бота для уведомлений в отдельной задаче
            notification_task = asyncio.create_task(self.start_notification_bot())
            logger.info(f"{Fore.GREEN}Бот уведомлений запущен{Style.RESET_ALL}")
        except Exception as e:
            logger.error(f"{Fore.RED}Ошибка запуска бота уведомлений: {e}{Style.RESET_ALL}")
        
        # Запускаем клиенты для всех аккаунтов
        tasks = []
        for account in self.accounts:
            task = asyncio.create_task(self.run_client(account))
            tasks.append(task)
        
        # Ожидаем завершения всех задач
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info(f"{Fore.YELLOW}Задачи клиентов отменены{Style.RESET_ALL}")
        except Exception as e:
            logger.error(f"{Fore.RED}Ошибка при выполнении задач клиентов: {e}{Style.RESET_ALL}")
        
        # Останавливаем бота уведомлений
        try:
            await self.stop_notification_bot()
            logger.info(f"{Fore.YELLOW}Бот уведомлений остановлен{Style.RESET_ALL}")
        except Exception as e:
            logger.error(f"{Fore.RED}Ошибка остановки бота уведомлений: {e}{Style.RESET_ALL}")
    
    async def start_notification_bot(self):
        """Запуск бота для уведомлений"""
        try:
            from notification_bot import NotificationBot
            self.notification_bot = NotificationBot()
            await self.notification_bot.start()
            logger.info(f"{Fore.GREEN}Бот уведомлений запущен{Style.RESET_ALL}")
            return True
        except Exception as e:
            logger.error(f"{Fore.RED}Ошибка запуска бота уведомлений: {e}{Style.RESET_ALL}")
            self.notification_bot = None  # Обнуляем при ошибке
            return False

    async def stop_notification_bot(self):
        """Остановка бота для уведомлений"""
        try:
            if hasattr(self, 'notification_bot') and self.notification_bot:
                await self.notification_bot.stop()
                self.notification_bot = None  # Обнуляем после остановки
                logger.info(f"{Fore.GREEN}Бот уведомлений остановлен{Style.RESET_ALL}")
        except Exception as e:
            logger.error(f"{Fore.RED}Ошибка остановки бота уведомлений: {e}{Style.RESET_ALL}")
    
    def add_account(self):
        """Добавление нового аккаунта с немедленной авторизацией"""
        if len(self.accounts) >= 4:
            print(f"{Fore.RED}Достигнут максимальный лимит аккаунтов (4){Style.RESET_ALL}")
            return False
        
        account_name = input(f"{Fore.YELLOW}Введите название аккаунта (для вашего удобства): {Style.RESET_ALL}")
        
        # Создаем данные аккаунта
        account_data = {
            "name": account_name,
            "phone": "новый",
            "session_file": f"telegram_session_{len(self.accounts) + 1}"
        }
        
        # Сначала добавляем аккаунт в список
        self.accounts.append(account_data)
        self.save_accounts()
        
        print(f"{Fore.YELLOW}Выполняем авторизацию для аккаунта {account_name}...{Style.RESET_ALL}")
        
        # Выполняем авторизацию
        success = self.loop.run_until_complete(self.authenticate_account(self.clients[account_data['phone']], account_data))
        
        if success:
            print(f"{Fore.GREEN}Аккаунт {account_name} успешно добавлен и авторизован{Style.RESET_ALL}")
            return True
        else:
            # Если авторизация не удалась, удаляем аккаунт из списка
            self.accounts.pop()
            self.save_accounts()
            print(f"{Fore.RED}Не удалось авторизовать аккаунт {account_name}. Аккаунт не добавлен.{Style.RESET_ALL}")
            return False
    
    def remove_account(self):
        """Удаление существующего аккаунта"""
        if not self.accounts:
            print(f"{Fore.RED}Нет добавленных аккаунтов{Style.RESET_ALL}")
            return False
        
        print(f"{Fore.YELLOW}Список аккаунтов:{Style.RESET_ALL}")
        for i, account in enumerate(self.accounts, 1):
            print(f"{i}. {account['name']} ({account['phone']})")
        
        try:
            choice = int(input(f"{Fore.YELLOW}Выберите номер аккаунта для удаления (0 для отмены): {Style.RESET_ALL}"))
            if choice == 0:
                return False
            if 1 <= choice <= len(self.accounts):
                account = self.accounts.pop(choice - 1)
                self.save_accounts()
                
                # Удаление файлов сессии
                session_file = account['session_file']
                try:
                    if os.path.exists(f"{session_file}.session"):
                        os.remove(f"{session_file}.session")
                    if os.path.exists(f"{session_file}.db"):
                        os.remove(f"{session_file}.db")
                except Exception as e:
                    logger.error(f"{Fore.RED}Ошибка удаления файлов сессии: {e}{Style.RESET_ALL}")
                
                print(f"{Fore.GREEN}Аккаунт {account['name']} удален{Style.RESET_ALL}")
                return True
            else:
                print(f"{Fore.RED}Неверный выбор{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.RED}Пожалуйста, введите число{Style.RESET_ALL}")
        
        return False
    
    def show_menu(self):
        """Показать меню управления аккаунтами"""
        while True:
            print(f"\n{Fore.CYAN}======== УПРАВЛЕНИЕ АККАУНТАМИ ========{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}Текущие аккаунты ({len(self.accounts)}/4):{Style.RESET_ALL}")
            
            if not self.accounts:
                print("Нет добавленных аккаунтов")
            else:
                for i, account in enumerate(self.accounts, 1):
                    print(f"{i}. {account['name']} ({account['phone']})")
            
            print(f"\n{Fore.CYAN}Выберите действие:{Style.RESET_ALL}")
            print(f"{Fore.WHITE}1. Добавить аккаунт{Style.RESET_ALL}")
            print(f"{Fore.WHITE}2. Удалить аккаунт{Style.RESET_ALL}")
            print(f"{Fore.WHITE}3. Запустить бота{Style.RESET_ALL}")
            print(f"{Fore.WHITE}4. Выйти{Style.RESET_ALL}")
            
            try:
                choice = int(input(f"{Fore.CYAN}Ваш выбор: {Style.RESET_ALL}"))
                if choice == 1:
                    self.add_account()
                elif choice == 2:
                    self.remove_account()
                elif choice == 3:
                    if not self.accounts:
                        print(f"{Fore.RED}Сначала добавьте хотя бы один аккаунт{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.GREEN}Запуск бота...{Style.RESET_ALL}")
                        return True
                elif choice == 4:
                    return False
                else:
                    print(f"{Fore.RED}Неверный выбор{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}Пожалуйста, введите число{Style.RESET_ALL}")

def main():
    parser = argparse.ArgumentParser(description='Telegram Online Status Bot')
    parser.add_argument('--use-proxy', action='store_true', help='Использовать SOCKS5 прокси (127.0.0.1:9050)')
    parser.add_argument('--setup', action='store_true', help='Запустить в режиме настройки')
    args = parser.parse_args()
    
    # Вывод информации о запуске
    print(f"{Fore.CYAN}=================================================={Style.RESET_ALL}")
    print(f"{Fore.GREEN}TELEGRAM ONLINE STATUS BOT (МУЛЬТИ-АККАУНТ){Style.RESET_ALL}")
    print(f"{Fore.GREEN}Автор: @imildar{Style.RESET_ALL}")
    print(f"{Fore.CYAN}=================================================={Style.RESET_ALL}")
    
    logger.info(f"{Fore.CYAN}=================================================={Style.RESET_ALL}")
    logger.info(f"{Fore.GREEN}TELEGRAM ONLINE STATUS BOT (МУЛЬТИ-АККАУНТ){Style.RESET_ALL}")
    logger.info(f"{Fore.GREEN}Автор: @imildar{Style.RESET_ALL}")
    logger.info(f"{Fore.CYAN}=================================================={Style.RESET_ALL}")
    
    logger.info(f"{Fore.GREEN}Скрипт запущен{Style.RESET_ALL}")
    logger.info(f"{Fore.YELLOW}Версия Python: {sys.version}{Style.RESET_ALL}")
    logger.info(f"{Fore.YELLOW}Интервал обновления онлайн: {ONLINE_UPDATE_INTERVAL} секунд{Style.RESET_ALL}")
    
    # Создаем экземпляр бота
    bot = MultiAccountTelegramBot(use_proxy=args.use_proxy)
    
    # Если режим настройки или нет аккаунтов, показываем меню
    if args.setup or not bot.accounts:
        if not bot.show_menu():
            logger.info(f"{Fore.YELLOW}Выход из программы{Style.RESET_ALL}")
            return
    
    # Запускаем всех клиентов
    try:
        asyncio.run(bot.start_all_clients())
    except KeyboardInterrupt:
        logger.info(f"{Fore.YELLOW}Получен сигнал завершения работы{Style.RESET_ALL}")
    except Exception as e:
        logger.error(f"{Fore.RED}Критическая ошибка: {e}{Style.RESET_ALL}")
    finally:
        logger.info(f"{Fore.YELLOW}Программа завершена{Style.RESET_ALL}")

if __name__ == "__main__":
    main()
