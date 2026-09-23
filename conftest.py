# Root conftest: pytest puts the project root on sys.path
# (lets tests import top-level modules: engine, aim_metrics, evaluate_mae).
import os

# backend.main вызывает load_dotenv() на импорте, и AUTH_MODE=discord из
# локального .env превращал анонимные тесты в 401. load_dotenv не
# перезаписывает уже заданные переменные — фиксируем дефолт до импорта.
# Тесты авторизации включают discord сами через monkeypatch.setenv.
os.environ["AUTH_MODE"] = "off"
