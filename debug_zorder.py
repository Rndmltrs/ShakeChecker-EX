import time
import win32gui
import win32con
import win32process

def get_z_order():
    z_order = []
    
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            
            # Show if it belongs to one of our target window classes or titles
            is_qt = "Qt" in class_name or "QWidget" in class_name
            is_game = "Poke" in title or "Pokе" in title or "GLFW" in class_name or "SunAwt" in class_name or "LWJGL" in class_name
            
            if is_qt or is_game:
                ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                topmost = bool(ex_style & win32con.WS_EX_TOPMOST)
                layered = bool(ex_style & win32con.WS_EX_LAYERED)
                transparent = bool(ex_style & win32con.WS_EX_TRANSPARENT)
                
                owner = win32gui.GetWindow(hwnd, win32con.GW_OWNER)
                
                flags = []
                if topmost: flags.append("TOPMOST")
                if layered: flags.append("LAYERED")
                if transparent: flags.append("TRANSPARENT")
                if owner: flags.append(f"OWNED_BY:{owner}")
                
                z_order.append(f"[{hwnd}] PID:{pid} | {title[:20]:<20} | {class_name[:20]:<20} | {' '.join(flags)}")
    
    win32gui.EnumWindows(callback, None)
    return z_order

def main():
    print("Starting Z-Order Debugger for PokeMMO & ShakeChecker...")
    print("This will print the Z-order of relevant windows. Press Ctrl+C to stop.\n")
    
    last_state = []
    try:
        while True:
            current_state = get_z_order()
            if current_state != last_state:
                print(f"--- Z-Order Changed at {time.strftime('%H:%M:%S')} ---")
                for i, line in enumerate(current_state):
                    print(f"{i:02d}: {line}")
                print("-" * 40)
                last_state = current_state
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Stopped.")

if __name__ == "__main__":
    main()
