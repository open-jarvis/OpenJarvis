"""Herramientas de control del PC para Jarvis.

Se prueban con un "PC falso" que registra las acciones en vez de ejecutarlas,
así la lógica (búsqueda de apps, carpetas, enlaces) se verifica en cualquier
sistema operativo.
"""

from __future__ import annotations

import pytest

from openjarvis.tools import pc_control
from openjarvis.tools.pc_control import (
    LockComputerTool,
    MediaControlTool,
    OpenAppTool,
    OpenFolderTool,
    OpenWebsiteTool,
    PlayYoutubeTool,
    WhatsappMessageTool,
    find_app,
)

START_APPS = [
    {"Name": "Google Chrome", "AppID": "Chrome"},
    {"Name": "Microsoft Edge", "AppID": "MSEdge"},
    {"Name": "Bloc de notas", "AppID": "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"},
    {"Name": "Calculadora", "AppID": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"},
    {"Name": "Spotify", "AppID": "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"},
    {"Name": "Word", "AppID": "Microsoft.Office.WINWORD.EXE.15"},
    {"Name": "Visual Studio Code", "AppID": "Microsoft.VisualStudioCode"},
]


class FakePlatform:
    """PC falso: guarda lo que se pidió hacer."""

    is_windows = True

    def __init__(self, apps=START_APPS, page=""):
        self.apps = apps
        self.page = page
        self.opened: list[str] = []
        self.launched: list[str] = []
        self.keys: list[tuple[int, int]] = []
        self.locked = False

    def list_start_apps(self):
        return self.apps

    def launch_app(self, app_id):
        self.launched.append(app_id)

    def open(self, target):
        self.opened.append(target)

    def press_key(self, vk, times):
        self.keys.append((vk, times))

    def lock(self):
        self.locked = True

    def known_folder(self, folder_id):
        return f"C:/Users/juan/{folder_id}"

    def fetch(self, url):
        return self.page


@pytest.fixture
def pc(monkeypatch):
    fake = FakePlatform()
    monkeypatch.setattr(pc_control, "_platform", fake)
    pc_control._clear_app_cache()
    return fake


# --- Abrir apps -------------------------------------------------------------


@pytest.mark.parametrize(
    "spoken, app_id",
    [
        ("chrome", "Chrome"),
        ("Google Chrome", "Chrome"),
        ("bloc de notas", "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"),
        ("notepad", "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"),
        ("la calculadora", "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"),
        ("calculator", "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"),
        ("espotifai", "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"),
        ("vs code", "Microsoft.VisualStudioCode"),
        ("el navegador", "MSEdge"),
    ],
)
def test_find_app_understands_spoken_names(spoken, app_id):
    match = find_app(spoken, START_APPS)
    assert match is not None and match["AppID"] == app_id


def test_find_app_returns_none_for_unknown_app():
    assert find_app("photoshop", START_APPS) is None


def test_open_app_launches_the_matching_app(pc):
    result = OpenAppTool().execute(name="abre spotify")
    assert result.success
    assert pc.launched == ["SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"]
    assert "Spotify" in result.content


def test_open_app_suggests_alternatives_when_unsure(pc):
    result = OpenAppTool().execute(name="photoshop")
    assert not result.success
    assert pc.launched == []
    assert "No encontré" in result.content


# --- Web --------------------------------------------------------------------


def test_open_website_opens_urls_and_domains(pc):
    assert OpenWebsiteTool().execute(target="https://unal.edu.co").success
    OpenWebsiteTool().execute(target="github.com")
    assert pc.opened == ["https://unal.edu.co", "https://github.com"]


def test_open_website_searches_plain_text(pc):
    OpenWebsiteTool().execute(target="clima en Bogotá")
    assert pc.opened == ["https://www.google.com/search?q=clima+en+Bogot%C3%A1"]


def test_open_website_rejects_dangerous_schemes(pc):
    OpenWebsiteTool().execute(target="file:///C:/Windows/System32/cmd.exe")
    assert pc.opened[0].startswith("https://www.google.com/search?q=")


def test_play_youtube_opens_the_first_video(pc):
    pc.page = 'xx "videoId":"dQw4w9WgXcQ" yy "videoId":"aaaaaaaaaaa"'
    result = PlayYoutubeTool().execute(query="lofi para estudiar")
    assert result.success
    assert pc.opened == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]


def test_play_youtube_falls_back_to_results_page(pc):
    pc.page = "sin resultados reconocibles"
    PlayYoutubeTool().execute(query="lofi")
    assert pc.opened == ["https://www.youtube.com/results?search_query=lofi"]


# --- Medios y sistema -------------------------------------------------------


def test_media_control_presses_media_keys(pc):
    MediaControlTool().execute(action="play_pause")
    MediaControlTool().execute(action="volume_up", steps=3)
    assert pc.keys == [(0xB3, 1), (0xAF, 3)]


def test_media_control_rejects_unknown_actions(pc):
    result = MediaControlTool().execute(action="apagar")
    assert not result.success
    assert pc.keys == []


def test_lock_computer(pc):
    assert LockComputerTool().execute().success
    assert pc.locked


# --- Carpetas ---------------------------------------------------------------


@pytest.mark.parametrize(
    "spoken, folder",
    [
        ("descargas", "downloads"),
        ("Documentos", "documents"),
        ("escritorio", "desktop"),
    ],
)
def test_open_folder_opens_known_folders(pc, spoken, folder):
    result = OpenFolderTool().execute(name=spoken)
    assert result.success
    assert pc.opened == [f"C:/Users/juan/{folder}"]


def test_open_folder_rejects_unknown_names(pc):
    result = OpenFolderTool().execute(name="C:/Windows/System32")
    assert not result.success
    assert pc.opened == []


# --- WhatsApp ---------------------------------------------------------------


def test_whatsapp_message_prepares_chat_without_sending(pc):
    result = WhatsappMessageTool().execute(
        text="Hola, ya voy", phone="+57 300 123 4567"
    )
    assert result.success
    assert pc.opened == ["whatsapp://send?phone=573001234567&text=Hola%2C+ya+voy"]
    assert "Enter" in result.content


def test_whatsapp_message_without_phone_opens_picker(pc):
    WhatsappMessageTool().execute(text="Hola")
    assert pc.opened == ["whatsapp://send?text=Hola"]


# --- Fuera de Windows -------------------------------------------------------


def test_desktop_tools_explain_when_not_on_windows(pc):
    pc.is_windows = False
    result = OpenAppTool().execute(name="chrome")
    assert not result.success
    assert "Windows" in result.content
