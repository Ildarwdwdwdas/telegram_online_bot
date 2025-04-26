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

# API-ключи Telegram
API_ID = 23392898
API_HASH = "8bb33954756ad65e785b24a3db786386"

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
    backupCount=5
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
    maxBytes=10 * 1024 * 1024,  # 10 МБ
    backupCount=5
)
message_file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-7s | %(message)s', '%Y-%m-%d %H:%M:%S'))
message_logger.addHandler(message_file_handler)

# Интервал обновления статуса онлайн (в секундах)
ONLINE_UPDATE_INTERVAL = 3

# Путь к файлу с данными аккаунтов
ACCOUNTS_FILE = 'telegram_accounts.json'

class MultiAccountTelegramBot:
    def __init__(self, use_proxy=False):
        self.use_proxy = use_proxy
        self.accounts = self.load_accounts()
        self.clients = {}
        self.is_running = True
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
    def load_accounts(self):
        """Загрузка данных аккаунтов из файла"""
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, 'r') as f:
                    return json.load(f)
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
        
        # Если сессия существует, пробуем автоматический вход
        if session_exists:
            logger.info(f"{Fore.YELLOW}Попытка автоматического входа с номером: {phone}{Style.RESET_ALL}")
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    await client.start(phone=lambda: phone)
                logger.info(f"{Fore.GREEN}Авторизация для {phone} успешна!{Style.RESET_ALL}")
            except Exception as e:
                logger.error(f"{Fore.RED}Ошибка автоматического входа для {phone}: {e}{Style.RESET_ALL}")
                # Если не получилось, пробуем ручной вход
                try:
                    await client.start(phone=lambda: input(f'{Fore.YELLOW}Введите номер телефона для {account_data["name"]}: {Style.RESET_ALL}'))
                    logger.info(f"{Fore.GREEN}Вход выполнен вручную для {phone}{Style.RESET_ALL}")
                    
                    # Обновляем номер в данных аккаунта, если он был изменен
                    actual_user = await client.get_me()
                    if hasattr(actual_user, 'phone'):
                        account_data['phone'] = actual_user.phone
                        self.save_accounts()
                except Exception as e2:
                    logger.error(f"{Fore.RED}Не удалось войти для {phone}: {e2}{Style.RESET_ALL}")
                    return None
        else:
            # Если сессии нет, запрашиваем номер телефона и код
            try:
                await client.start(phone=lambda: input(f'{Fore.YELLOW}Введите номер телефона для {account_data["name"]}: {Style.RESET_ALL}'))
                logger.info(f"{Fore.GREEN}Новая авторизация успешна!{Style.RESET_ALL}")
                
                # Обновляем номер в данных аккаунта
                actual_user = await client.get_me()
                if hasattr(actual_user, 'phone'):
                    account_data['phone'] = actual_user.phone
                    self.save_accounts()
                    logger.info(f"{Fore.GREEN}Номер телефона обновлен: {account_data['phone']}{Style.RESET_ALL}")
            except Exception as e:
                logger.error(f"{Fore.RED}Ошибка авторизации: {e}{Style.RESET_ALL}")
                return None
        
        # Загружаем последние диалоги для кэширования сущностей
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
        except Exception as e:
            logger.error(f"{Fore.RED}[{phone}] Ошибка загрузки диалогов: {e}{Style.RESET_ALL}")
        
        # Настраиваем обработчик сообщений для этого клиента
        @client.on(events.NewMessage)
        async def handler(event):
            try:
                if event.is_private:
                    # Безопасно получаем ID чата/пользователя
                    chat_id = event.chat_id
                    
                    # Пытаемся отметить сообщение как прочитанное безопасным способом
                    try:
                        # Получаем текст сообщения безопасно
                        message_text = event.message.text if hasattr(event.message, 'text') else "[Медиа или не текстовое сообщение]"
                        
                        # Получаем информацию об отправителе безопасным способом
                        try:
                            sender = await event.get_sender()
                            username = (
                                getattr(sender, 'username', None) or 
                                getattr(sender, 'phone', None) or 
                                f"user_{utils.get_peer_id(sender) if hasattr(utils, 'get_peer_id') else chat_id}"
                            )
                        except Exception:
                            username = f"user_{chat_id}"
                            
                        message_logger.info(f"{Fore.GREEN}[{phone}] Получено сообщение от {username}: {message_text}{Style.RESET_ALL}")
                        
                        # Метод 1: Стандартный API
                        try:
                            await client.send_read_acknowledge(chat_id)
                            message_logger.info(f"{Fore.GREEN}[{phone}] Сообщение от {username} отмечено как прочитанное{Style.RESET_ALL}")
                            return  # Если успешно, выходим из функции
                        except Exception as e:
                            # Если не сработал стандартный метод, пробуем альтернативы
                            if "Could not find the input entity for" in str(e):
                                pass  # Продолжаем к следующему методу
                            else:
                                logger.error(f"{Fore.YELLOW}[{phone}] Метод 1 не удался: {str(e)[:100]}{Style.RESET_ALL}")
                        
                        # Метод 2: Через сырой API запрос
                        try:
                            # Используем более низкоуровневый метод
                            result = await client(functions.messages.ReadHistoryRequest(
                                peer=chat_id,
                                max_id=event.message.id
                            ))
                            message_logger.info(f"{Fore.GREEN}[{phone}] Сообщение от {username} отмечено как прочитанное (метод 2){Style.RESET_ALL}")
                            return  # Если успешно, выходим из функции
                        except Exception as e:
                            logger.error(f"{Fore.YELLOW}[{phone}] Метод 2 не удался: {str(e)[:100]}{Style.RESET_ALL}")
                        
                        # Метод 3: Принудительное получение entity
                        try:
                            # Пытаемся получить entity через get_input_entity
                            input_entity = await client.get_input_entity(chat_id)
                            # Теперь пробуем отметить как прочитанное
                            await client(functions.messages.ReadHistoryRequest(
                                peer=input_entity,
                                max_id=event.message.id
                            ))
                            message_logger.info(f"{Fore.GREEN}[{phone}] Сообщение от {username} отмечено как прочитанное (метод 3){Style.RESET_ALL}")
                        except Exception as e:
                            logger.error(f"{Fore.RED}[{phone}] Не удалось отметить сообщение: {str(e)[:100]}{Style.RESET_ALL}")
                            # На этом этапе, если все методы не сработали, просто логируем ошибку
                    except Exception as e:
                        logger.error(f"{Fore.RED}[{phone}] Общая ошибка: {str(e)[:100]}{Style.RESET_ALL}")
            except Exception as e:
                logger.error(f"{Fore.RED}[{phone}] Ошибка обработки сообщения: {e}{Style.RESET_ALL}")
        
        logger.info(f"{Fore.GREEN}Клиент для {account_data['phone']} настроен и готов{Style.RESET_ALL}")
        # Отключаем клиента после настройки, он будет подключен снова при запуске
        await client.disconnect()
        return True
    
    async def run_client(self, account_data):
        """Запуск клиента с периодическим обновлением статуса online"""
        session_file = account_data['session_file']
        phone = account_data['phone']
        
        # Создаем клиента заново
        client = self.create_client(session_file)
        
        try:
            # Подключаемся и проверяем авторизацию
            await client.connect()
            if not await client.is_user_authorized():
                logger.error(f"{Fore.RED}Клиент для {phone} не авторизован. Попробуйте перенастроить аккаунт.{Style.RESET_ALL}")
                return
            
            self.clients[phone] = client
            logger.info(f"{Fore.GREEN}Клиент для {phone} запущен успешно{Style.RESET_ALL}")
            
            # Загружаем последние диалоги для кэширования сущностей
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
            except Exception as e:
                logger.error(f"{Fore.RED}[{phone}] Ошибка загрузки диалогов: {e}{Style.RESET_ALL}")
            
            # Настраиваем обработчик сообщений
            @client.on(events.NewMessage)
            async def handler(event):
                try:
                    if event.is_private:
                        # Безопасно получаем ID чата/пользователя
                        chat_id = event.chat_id
                        
                        # Пытаемся отметить сообщение как прочитанное безопасным способом
                        try:
                            # Получаем текст сообщения безопасно
                            message_text = event.message.text if hasattr(event.message, 'text') else "[Медиа или не текстовое сообщение]"
                            
                            # Получаем информацию об отправителе безопасным способом
                            try:
                                sender = await event.get_sender()
                                username = (
                                    getattr(sender, 'username', None) or 
                                    getattr(sender, 'phone', None) or 
                                    f"user_{utils.get_peer_id(sender) if hasattr(utils, 'get_peer_id') else chat_id}"
                                )
                            except Exception:
                                username = f"user_{chat_id}"
                                
                            message_logger.info(f"{Fore.GREEN}[{phone}] Получено сообщение от {username}: {message_text}{Style.RESET_ALL}")
                            
                            # Метод 1: Стандартный API
                            try:
                                await client.send_read_acknowledge(chat_id)
                                message_logger.info(f"{Fore.GREEN}[{phone}] Сообщение от {username} отмечено как прочитанное{Style.RESET_ALL}")
                                return  # Если успешно, выходим из функции
                            except Exception as e:
                                # Если не сработал стандартный метод, пробуем альтернативы
                                if "Could not find the input entity for" in str(e):
                                    pass  # Продолжаем к следующему методу
                                else:
                                    logger.error(f"{Fore.YELLOW}[{phone}] Метод 1 не удался: {str(e)[:100]}{Style.RESET_ALL}")
                            
                            # Метод 2: Через сырой API запрос
                            try:
                                # Используем более низкоуровневый метод
                                result = await client(functions.messages.ReadHistoryRequest(
                                    peer=chat_id,
                                    max_id=event.message.id
                                ))
                                message_logger.info(f"{Fore.GREEN}[{phone}] Сообщение от {username} отмечено как прочитанное (метод 2){Style.RESET_ALL}")
                                return  # Если успешно, выходим из функции
                            except Exception as e:
                                logger.error(f"{Fore.YELLOW}[{phone}] Метод 2 не удался: {str(e)[:100]}{Style.RESET_ALL}")
                            
                            # Метод 3: Принудительное получение entity
                            try:
                                # Пытаемся получить entity через get_input_entity
                                input_entity = await client.get_input_entity(chat_id)
                                # Теперь пробуем отметить как прочитанное
                                await client(functions.messages.ReadHistoryRequest(
                                    peer=input_entity,
                                    max_id=event.message.id
                                ))
                                message_logger.info(f"{Fore.GREEN}[{phone}] Сообщение от {username} отмечено как прочитанное (метод 3){Style.RESET_ALL}")
                            except Exception as e:
                                logger.error(f"{Fore.RED}[{phone}] Не удалось отметить сообщение: {str(e)[:100]}{Style.RESET_ALL}")
                                # На этом этапе, если все методы не сработали, просто логируем ошибку
                        except Exception as e:
                            logger.error(f"{Fore.RED}[{phone}] Общая ошибка: {str(e)[:100]}{Style.RESET_ALL}")
                except Exception as e:
                    logger.error(f"{Fore.RED}[{phone}] Ошибка обработки сообщения: {e}{Style.RESET_ALL}")
            
            # Запускаем цикл обновления статуса
            while self.is_running:
                try:
                    # Обновляем статус онлайн
                    await client(functions.account.UpdateStatusRequest(offline=False))
                    logger.info(f"{Fore.CYAN}[{phone}] Статус онлайн обновлен...{Style.RESET_ALL}")
                    
                    # Ждем некоторое время (3 секунды)
                    await asyncio.sleep(ONLINE_UPDATE_INTERVAL)
                except Exception as e:
                    logger.error(f"{Fore.RED}[{phone}] Ошибка обновления статуса: {e}{Style.RESET_ALL}")
                    await asyncio.sleep(5)  # В случае ошибки подождем немного дольше
            
        finally:
            # При выходе из цикла отключаем клиент
            await client.disconnect()
            logger.info(f"{Fore.YELLOW}[{phone}] Клиент отключен{Style.RESET_ALL}")
    
    async def start_all_clients(self):
        """Запуск всех клиентов"""
        tasks = []
        for account_data in self.accounts:
            tasks.append(self.run_client(account_data))
        
        await asyncio.gather(*tasks)
    
    async def authenticate_account(self, account_data):
        """Выполняет авторизацию для аккаунта"""
        return await self.setup_client(account_data)
    
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
        success = self.loop.run_until_complete(self.authenticate_account(account_data))
        
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
