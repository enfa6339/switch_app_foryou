"""
Auto-Language Switcher — เวอร์ชันหน้าต่าง
ไฮไลต์ข้อความ แล้วกด Ctrl+Q เพื่อสลับ อังกฤษ <-> ไทย (แป้นเกษมณี)
มีปุ่มเดียว: เปิด/ปิดการทำงาน

ติดตั้ง:  pip install pyperclip
รัน:      ดับเบิลคลิกไฟล์นี้ (.pyw = ไม่มีหน้าต่างคอนโซล)
"""

import ctypes
import threading
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import messagebox

import pyperclip

# ------------------------- ตั้งค่า -------------------------
COPY_TIMEOUT = 1.5           # วินาทีที่รอให้ข้อความเข้า Clipboard
RESTORE_CLIPBOARD = False    # True = คืนค่า Clipboard เดิมหลังวางเสร็จ
# -----------------------------------------------------------

# ---------- แผนที่แป้นพิมพ์เกษมณี ----------
EN_NORMAL = "`1234567890-=qwertyuiop[]\\asdfghjkl;'zxcvbnm,./"
TH_NORMAL = "_ๅ/-ภถุึคตจขชๆไำพะัีรนยบลฃฟหกดเ้่าสวงผปแอิืทมใฝ"
EN_SHIFT = '~!@#$%^&*()_+QWERTYUIOP{}|ASDFGHJKL:"ZXCVBNM<>?'
TH_SHIFT = '%+๑๒๓๔ู฿๕๖๗๘๙๐"ฎฑธํ๊ณฯญฐ,ฅฤฆฏโฌ็๋ษศซ.()ฉฮฺ์?ฒฬฦ'

assert len(EN_NORMAL) == len(TH_NORMAL) == 47, "แผนที่ปุ่มปกติไม่ครบ"
assert len(EN_SHIFT) == len(TH_SHIFT) == 47, "แผนที่ปุ่ม Shift ไม่ครบ"

EN2TH = dict(zip(EN_NORMAL + EN_SHIFT, TH_NORMAL + TH_SHIFT))
TH2EN = {
    th: en
    for en, th in zip(EN_NORMAL + EN_SHIFT, TH_NORMAL + TH_SHIFT)
    if "\u0E00" <= th <= "\u0E7F"
}


def has_thai(text: str) -> bool:
    return any("\u0E00" <= ch <= "\u0E7F" for ch in text)


def convert(text: str) -> str:
    mapping = TH2EN if has_thai(text) else EN2TH
    return "".join(mapping.get(ch, ch) for ch in text)


# ---------- Windows API ----------
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

MOD_CONTROL, MOD_NOREPEAT = 0x0002, 0x4000
WM_USER, WM_QUIT, WM_HOTKEY = 0x0400, 0x0012, 0x0312
KEYEVENTF_KEYUP = 0x0002
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
VK_C, VK_V, VK_Q = 0x43, 0x56, 0x51
ID_SWITCH = 1


def _down(vk):
    user32.keybd_event(vk, 0, 0, 0)


def _up(vk):
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def send_ctrl(vk):
    _down(VK_CONTROL)
    _down(vk)
    _up(vk)
    _up(VK_CONTROL)


def wait_release(timeout=2.0):
    end = time.time() + timeout
    keys = (VK_CONTROL, VK_SHIFT, VK_MENU, VK_Q)
    while time.time() < end:
        if not any(user32.GetAsyncKeyState(k) & 0x8000 for k in keys):
            return
        time.sleep(0.01)


def grab_selection():
    pyperclip.copy("")                 # เคลียร์ Clipboard กันข้อความค้าง
    send_ctrl(VK_C)
    end = time.time() + COPY_TIMEOUT
    while time.time() < end:
        time.sleep(0.05)
        text = pyperclip.paste()
        if text:
            return text
    return ""


_lock = threading.Lock()


def do_switch():
    if not _lock.acquire(blocking=False):
        return
    try:
        original = pyperclip.paste() if RESTORE_CLIPBOARD else None
        wait_release()
        selected = grab_selection()
        if not selected:
            if original is not None:
                pyperclip.copy(original)
            return
        pyperclip.copy(convert(selected))
        time.sleep(0.08)
        send_ctrl(VK_V)
        if original is not None:
            time.sleep(0.3)
            pyperclip.copy(original)
    except Exception:
        pass
    finally:
        _lock.release()


class HotkeyListener:
    """เธรดที่ลงทะเบียน Ctrl+Q และรอรับ WM_HOTKEY; หยุดได้โดยส่ง WM_QUIT"""

    def __init__(self):
        self.thread = None
        self.tid = None
        self.error = None

    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self) -> bool:
        if self.running():
            return True
        self.error = None
        ready = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self.thread.start()
        ready.wait(2)
        return self.error is None

    def _run(self, ready):
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, WM_USER, WM_USER, 0)  # สร้างคิวข้อความของเธรด
        self.tid = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, ID_SWITCH, MOD_CONTROL | MOD_NOREPEAT, VK_Q):
            self.error = ctypes.get_last_error() or -1
            ready.set()
            return
        ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == ID_SWITCH:
                    threading.Thread(target=do_switch, daemon=True).start()
        finally:
            user32.UnregisterHotKey(None, ID_SWITCH)

    def stop(self):
        if self.running() and self.tid:
            user32.PostThreadMessageW(self.tid, WM_QUIT, 0, 0)
            self.thread.join(timeout=1.5)
        self.thread = None


# ---------- หน้าต่าง ----------
class App:
    FONT = "Leelawadee UI"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.listener = HotkeyListener()

        root.title("Auto-Language Switcher")
        root.geometry("340x200")
        root.resizable(False, False)

        self.status = tk.Label(root, font=(self.FONT, 15, "bold"))
        self.status.pack(pady=(24, 4))

        tk.Label(
            root,
            text="ไฮไลต์ข้อความ แล้วกด Ctrl+Q\nเพื่อสลับ อังกฤษ ↔ ไทย",
            font=(self.FONT, 10),
            fg="#555555",
        ).pack()

        self.btn = tk.Button(root, font=(self.FONT, 12), width=16, command=self.toggle)
        self.btn.pack(pady=18)

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.turn_on()

    def show(self, on: bool):
        if on:
            self.status.config(text="● เปิดอยู่", fg="#1a8a3a")
            self.btn.config(text="ปิดการทำงาน")
        else:
            self.status.config(text="● ปิดอยู่", fg="#c0392b")
            self.btn.config(text="เปิดการทำงาน")

    def turn_on(self):
        if self.listener.start():
            self.show(True)
        else:
            self.show(False)
            messagebox.showerror(
                "เปิดไม่สำเร็จ",
                "ลงทะเบียนคีย์ลัด Ctrl+Q ไม่ได้\nอาจมีโปรแกรมอื่นใช้คีย์นี้อยู่ ลองปิดโปรแกรมนั้นก่อน",
            )

    def turn_off(self):
        self.listener.stop()
        self.show(False)

    def toggle(self):
        if self.listener.running():
            self.turn_off()
        else:
            self.turn_on()

    def on_close(self):
        self.listener.stop()
        self.root.destroy()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # ให้ตัวหนังสือคมบนจอความละเอียดสูง
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
