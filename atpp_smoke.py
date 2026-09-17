import os, sys, traceback
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"D:\自研软件\AT小PP")
from unittest.mock import MagicMock
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QMimeData, QUrl, QPoint
from PyQt6.QtGui import QDragEnterEvent

app = QApplication([])
from app.ui.music_player import MusicPlayer
from app.ui.pet_window import PetWindow


def sim_drag(win, name):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(r"D:\t.mp3")])
    ev = QDragEnterEvent(QPoint(0, 0), Qt.DropAction.CopyAction, mime,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    win.dragEnterEvent(ev)
    print("  ", name, "dragEnter accepted=", ev.isAccepted())


ctx = MagicMock()
try:
    p = MusicPlayer(ctx)
    print("MusicPlayer acceptDrops=", p.acceptDrops(), "| maskNull=", p.mask().isNull())
    sim_drag(p, "MusicPlayer")
except Exception as e:
    traceback.print_exc()
try:
    pet = PetWindow(ctx)
    print("PetWindow acceptDrops=", pet.acceptDrops())
    sim_drag(pet, "PetWindow")
except Exception as e:
    traceback.print_exc()
print("DONE")
