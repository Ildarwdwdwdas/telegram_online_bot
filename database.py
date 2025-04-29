import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

from config import DB_FILE

logger = logging.getLogger('telegram_online')

class MessageDatabase:
    def __init__(self):
        """Инициализация базы данных сообщений."""
        self.conn = None
        self.cursor = None
        self.connect()
        self.create_tables()
    
    def connect(self):
        """Подключение к базе данных."""
        try:
            self.conn = sqlite3.connect(DB_FILE)
            self.conn.row_factory = sqlite3.Row
            self.cursor = self.conn.cursor()
            logger.info(f"Подключение к базе данных {DB_FILE} установлено")
        except Exception as e:
            logger.error(f"Ошибка подключения к базе данных: {e}")
    
    def create_tables(self):
        """Создание необходимых таблиц, если они не существуют."""
        try:
            # Таблица для пользователей
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    phone TEXT,
                    last_message_time TIMESTAMP
                )
            ''')
            
            # Таблица для сообщений
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    message_text TEXT,
                    timestamp TIMESTAMP,
                    is_incoming BOOLEAN,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            self.conn.commit()
            logger.info("Таблицы базы данных успешно созданы")
        except Exception as e:
            logger.error(f"Ошибка создания таблиц базы данных: {e}")
    
    def save_message(self, user_id: int, username: str, first_name: str = "", 
                    last_name: str = "", phone: str = "", message_text: str = "", 
                    is_incoming: bool = True):
        """Сохранение сообщения в базе данных."""
        try:
            current_time = datetime.now()
            
            # Проверяем, существует ли пользователь
            self.cursor.execute(
                "SELECT id FROM users WHERE id = ?", (user_id,)
            )
            user_exists = self.cursor.fetchone()
            
            # Если пользователя нет, добавляем его
            if not user_exists:
                self.cursor.execute(
                    "INSERT INTO users (id, username, first_name, last_name, phone, last_message_time) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, username, first_name, last_name, phone, current_time)
                )
            else:
                # Обновляем информацию о пользователе
                self.cursor.execute(
                    "UPDATE users SET username = ?, first_name = ?, last_name = ?, phone = ?, last_message_time = ? WHERE id = ?",
                    (username, first_name, last_name, phone, current_time, user_id)
                )
            
            # Добавляем сообщение
            self.cursor.execute(
                "INSERT INTO messages (user_id, message_text, timestamp, is_incoming) VALUES (?, ?, ?, ?)",
                (user_id, message_text, current_time, is_incoming)
            )
            
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения сообщения: {e}")
            return False
    
    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Получение пользователя по его username."""
        try:
            # Удаляем символ @ из начала username, если он есть
            if username.startswith('@'):
                username = username[1:]
            
            self.cursor.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            )
            user = self.cursor.fetchone()
            
            if user:
                return dict(user)
            return None
        except Exception as e:
            logger.error(f"Ошибка получения пользователя по username: {e}")
            return None
    
    def get_messages_by_user_id(self, user_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Получение истории сообщений для указанного пользователя."""
        try:
            self.cursor.execute(
                "SELECT * FROM messages WHERE user_id = ? ORDER BY timestamp ASC LIMIT ?",
                (user_id, limit)
            )
            messages = self.cursor.fetchall()
            
            return [dict(message) for message in messages]
        except Exception as e:
            logger.error(f"Ошибка получения истории сообщений: {e}")
            return []
    
    def get_chat_history(self, username: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """Получение пользователя и истории его сообщений по username."""
        user = self.get_user_by_username(username)
        
        if user:
            messages = self.get_messages_by_user_id(user['id'])
            return user, messages
        
        return None, []
    
    def close(self):
        """Закрытие соединения с базой данных."""
        if self.conn:
            self.conn.close()
            logger.info("Соединение с базой данных закрыто")

# Создание глобального экземпляра БД
db = MessageDatabase()
