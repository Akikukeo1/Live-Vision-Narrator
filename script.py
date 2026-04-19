import argparse
import json
import os
import sys
import time

try:
    import pyautogui
except ImportError:
    raise ImportError(
        "pyautogui が見つかりません。\n"
        "先に `pip install pyautogui` を実行してください。"
    )

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError:
    tk = None

try:
    import keyboard
except ImportError:
    keyboard = None

CONFIG_FILE = "mouse_route.json"

DEFAULT_ROUTE = [
    {
        "x": 100,
        "y": 200,
        "move_duration": 0.5,
        "pause_after_move": 0.3,
        "click": False,
    },
    {
        "x": 300,
        "y": 400,
        "move_duration": 0.7,
        "pause_after_move": 0.3,
        "click": False,
    },
    {
        "x": 500,
        "y": 250,
        "move_duration": 0.5,
        "pause_after_move": 0.5,
        "click": True,
    },
]


def load_route():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception as exc:
            raise RuntimeError(f"{CONFIG_FILE} の読み込みに失敗しました: {exc}")
    return DEFAULT_ROUTE


def save_route(route):
    with open(CONFIG_FILE, "w", encoding="utf-8") as fp:
        json.dump(route, fp, ensure_ascii=False, indent=2)


def format_route_item(item, index):
    return (
        f"{index}. ({item['x']}, {item['y']}) dur={item['move_duration']}s "
        f"pause={item['pause_after_move']}s click={item['click']}"
    )


def run_route(route, rounds):
    pyautogui.FAILSAFE = True
    print("3秒後に巡回を開始します。キャンセルするには Ctrl+C または画面左上に移動してください。")
    time.sleep(3)

    current_round = 0
    try:
        while rounds == 0 or current_round < rounds:
            current_round += 1
            print(f"巡回 {current_round} 回目: {len(route)} 点を移動します。")

            for idx, item in enumerate(route, start=1):
                x = item["x"]
                y = item["y"]
                move_duration = item.get("move_duration", 0.5)
                pause_after_move = item.get("pause_after_move", 0.3)
                click = item.get("click", False)

                print(f"  {idx} / {len(route)}: ({x}, {y}) へ移動します。")
                pyautogui.moveTo(x, y, duration=move_duration)

                if click:
                    print("    クリックします。")
                    pyautogui.click()

                if pause_after_move > 0:
                    time.sleep(pause_after_move)

            if rounds == 0:
                print("無限巡回中。終了するには Ctrl+C または画面左上に移動してください。")
            else:
                print(f"{current_round} 回目の巡回が完了しました。")

    except KeyboardInterrupt:
        print("\nユーザーによって中断されました。スクリプトを終了します。")

    except Exception as exc:
        print(f"エラーが発生しました: {exc}")
        raise


def open_recorder(route):
    if tk is None:
        raise RuntimeError("tkinter が利用できません。Python の GUI モジュールを有効にしてください。")

    root = tk.Tk()
    root.title("マウス座標巡回 ルートエディタ")
    root.geometry("700x420")

    route_data = list(route)

    current_pos_var = tk.StringVar(value="現在のマウス座標: ---")
    status_var = tk.StringVar(value="画面上にマウスポインタを移動してから、F6 で追加してください。")

    def refresh_position():
        try:
            x, y = pyautogui.position()
            current_pos_var.set(f"現在のマウス座標: ({x}, {y})")
        except Exception:
            current_pos_var.set("現在のマウス座標: 取得できません")
        root.after(100, refresh_position)

    def update_listbox():
        listbox.delete(0, tk.END)
        for idx, item in enumerate(route_data, start=1):
            listbox.insert(tk.END, format_route_item(item, idx))

    def add_position():
        try:
            x, y = pyautogui.position()
            route_data.append({
                "x": x,
                "y": y,
                "move_duration": float(move_duration_var.get()),
                "pause_after_move": float(pause_after_var.get()),
                "click": click_var.get(),
            })
            update_listbox()
            status_var.set(f"({x}, {y}) を追加しました。")
        except Exception as exc:
            messagebox.showerror("エラー", f"座標の追加に失敗しました: {exc}")

    def add_position_event(event=None):
        add_position()

    def add_position_from_hotkey():
        root.after(0, add_position)

    def remove_selected():
        selection = listbox.curselection()
        if not selection:
            status_var.set("削除する行を選択してください。")
            return
        index = selection[0]
        route_data.pop(index)
        update_listbox()
        status_var.set(f"{index + 1} 行目を削除しました。")

    def move_up():
        selection = listbox.curselection()
        if not selection:
            status_var.set("移動する行を選択してください。")
            return
        index = selection[0]
        if index == 0:
            return
        route_data[index - 1], route_data[index] = route_data[index], route_data[index - 1]
        update_listbox()
        listbox.selection_set(index - 1)

    def move_down():
        selection = listbox.curselection()
        if not selection:
            status_var.set("移動する行を選択してください。")
            return
        index = selection[0]
        if index >= len(route_data) - 1:
            return
        route_data[index + 1], route_data[index] = route_data[index], route_data[index + 1]
        update_listbox()
        listbox.selection_set(index + 1)

    def save_and_close():
        try:
            save_route(route_data)
            root.destroy()
            print(f"{CONFIG_FILE} に保存しました。")
        except Exception as exc:
            messagebox.showerror("保存エラー", f"設定の保存に失敗しました: {exc}")

    top_frame = ttk.Frame(root, padding=10)
    top_frame.pack(fill=tk.X)

    ttk.Label(top_frame, textvariable=current_pos_var, font=(None, 12)).pack(anchor=tk.W)
    ttk.Label(top_frame, textvariable=status_var, font=(None, 10)).pack(anchor=tk.W, pady=(2, 8))
    ttk.Label(top_frame, text="F6 で現在位置を追加します。" + ("  (keyboard モジュールがある場合、Ctrl+Shift+A でも追加できます)" if keyboard is not None else ""), font=(None, 10, "italic")).pack(anchor=tk.W, pady=(0, 8))

    control_frame = ttk.Frame(root)
    control_frame.pack(fill=tk.X, padx=10)

    ttk.Label(control_frame, text="移動時間(s):").grid(row=0, column=0, sticky=tk.W)
    move_duration_var = tk.StringVar(value="0.5")
    ttk.Entry(control_frame, textvariable=move_duration_var, width=10).grid(row=0, column=1, sticky=tk.W)

    ttk.Label(control_frame, text="待機時間(s):").grid(row=0, column=2, sticky=tk.W, padx=(10, 0))
    pause_after_var = tk.StringVar(value="0.3")
    ttk.Entry(control_frame, textvariable=pause_after_var, width=10).grid(row=0, column=3, sticky=tk.W)

    click_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(control_frame, text="クリックする", variable=click_var).grid(row=0, column=4, sticky=tk.W, padx=(10, 0))

    ttk.Button(control_frame, text="現在位置を追加", command=add_position).grid(row=0, column=5, padx=(14, 0))
    root.bind("<F6>", add_position_event)
    if keyboard is not None:
        try:
            keyboard.add_hotkey("ctrl+shift+a", add_position_from_hotkey)
        except Exception:
            status_var.set("keyboard ホットキー登録に失敗しました。F6 を使ってください。")

    listbox = tk.Listbox(root, font=(None, 10), activestyle="none", selectbackground="#c0c0ff")
    listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=(8, 0))

    button_frame = ttk.Frame(root)
    button_frame.pack(fill=tk.X, padx=10, pady=8)

    ttk.Button(button_frame, text="▲ 上へ", command=move_up).grid(row=0, column=0, padx=4)
    ttk.Button(button_frame, text="▼ 下へ", command=move_down).grid(row=0, column=1, padx=4)
    ttk.Button(button_frame, text="削除", command=remove_selected).grid(row=0, column=2, padx=4)
    ttk.Button(button_frame, text="保存して閉じる", command=save_and_close).grid(row=0, column=3, padx=4)

    update_listbox()
    refresh_position()
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="マウス巡回スクリプト")
    parser.add_argument("--record", action="store_true", help="GUI で座標を記録・編集します。")
    parser.add_argument("--rounds", type=int, default=0, help="巡回回数。0 は無限ループ。")
    args = parser.parse_args()

    if args.record:
        route = load_route()
        open_recorder(route)
        sys.exit(0)

    route = load_route()
    print(f"{CONFIG_FILE} から {len(route)} 点を読み込みました。")
    run_route(route, args.rounds)


if __name__ == "__main__":
    main()
