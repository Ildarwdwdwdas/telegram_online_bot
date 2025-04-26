#!/bin/bash

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Функция для вывода сообщений
print_message() {
    echo -e "${CYAN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

# Проверка параметров
SETUP_MODE=false
for arg in "$@"; do
    if [ "$arg" == "--setup" ]; then
        SETUP_MODE=true
    fi
done

# Проверка наличия Python и создание виртуального окружения, если его нет
if [ ! -d "venv" ]; then
    print_message "${YELLOW}Виртуальное окружение не найдено. Создание...${NC}"
    python3 -m venv venv || { print_message "${RED}Ошибка создания виртуального окружения!${NC}"; exit 1; }
fi

# Активация виртуального окружения
source venv/bin/activate || { print_message "${RED}Ошибка активации виртуального окружения!${NC}"; exit 1; }

# Установка необходимых пакетов
print_message "${YELLOW}Установка необходимых пакетов...${NC}"
pip install telethon colorama || { print_message "${RED}Ошибка установки пакетов!${NC}"; exit 1; }

# Создание директории для логов
mkdir -p logs

# Проверка статуса screen-сессии
if screen -list | grep -q "tgbot"; then
    print_message "${YELLOW}Обнаружена запущенная сессия бота. Останавливаем...${NC}"
    screen -S tgbot -X quit
    sleep 2
fi

# Если это режим настройки, запускаем бот в интерактивном режиме
if [ "$SETUP_MODE" = true ]; then
    print_message "${GREEN}Запуск бота для настройки...${NC}"
    print_message "${YELLOW}После настройки бот будет автоматически запущен в фоновом режиме${NC}"
    print_message "${CYAN}==========================================================${NC}"
    
    # Запускаем в screen, чтобы иметь возможность отключиться
    screen -S tgbot -dm bash -c "source venv/bin/activate && python telegram_online.py --setup"
    screen -r tgbot
else
    # Просто запускаем бота в фоновом режиме
    print_message "${GREEN}Запуск бота в фоновом режиме...${NC}"
    screen -S tgbot -dm bash -c "source venv/bin/activate && python telegram_online.py"
    print_message "${GREEN}Бот запущен успешно! Для просмотра логов введите: screen -r tgbot${NC}"
    print_message "${YELLOW}Для отключения от просмотра логов нажмите CTRL+A, затем D${NC}"
    print_message "${YELLOW}Бот продолжит работать в фоновом режиме.${NC}"
fi
