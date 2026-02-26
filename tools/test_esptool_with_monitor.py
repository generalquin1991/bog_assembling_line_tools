#!/usr/bin/env python3
"""ESP 复位/下载/运行状态小测试工具。

提供几个实用模式：

  0) 仅打开串口，不主动改 RTS/DTR，监听几秒
     - 用来确认“打开串口本身”是否会引起复位/进入下载模式。

  1) RTS/DTR 扫描 + 手动记录 LED 行为
     - 依次切换几种 RTS/DTR 组合，你输入 0/1/2/3 描述 LED 行为；
     - 用来搞清楚 PC 的流控信号和板子 EN/BOOT 之间的真实关系。

  2) 强制进入下载模式 + 监听 bootloader 日志
     - 将芯片拉到 DOWNLOAD(UART0)，监听几秒钟 ROM 日志；
     - 用来验证“下载模式 + monitor”是否稳定。

  3) 空闲状态监听应用日志（不主动拉下载）
     - 将 RTS/DTR 释放到空闲 (False, False)，只做监听；
     - 你可以手动按板子上的复位键，看正常启动时应用日志和 LED 行为。

  4) 打开串口并监听，同时执行一次 esptool 命令
     - 保持当前监听，子进程里运行 esptool（不复位/不进下载）；
     - 用来观察在“应用运行状态”下，esptool 的失败行为。

  5) 先监听，再主动触发进入下载模式，然后在该状态下运行 esptool
     - 步骤：监听 → 手动/自动进入 DOWNLOAD(UART0) → esptool 使用 no_reset 直接连接；
     - 用来验证“先进入下载模式 + 再 run esptool”这条路径是否稳定。
"""

import sys
import threading
import time

import subprocess

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.wchusbserial110"
BAUD = 78400


def main():
    print(f"测试串口: {PORT}")
    print(f"波特率: {BAUD}\n")

    # 1. 打开串口
    print("步骤1: 打开串口...")
    ser = serial.Serial(PORT, BAUD, timeout=0.05)
    print(f"✓ 串口已打开: {ser.is_open}")

    # 一些驱动在打开时会默认设置 RTS/DTR，这里先打印一下当前状态
    print(f"当前 RTS: {ser.rts}, DTR: {ser.dtr}")

    # 2. 选择测试模式
    print(
        "\n请选择测试模式：\n"
        "  0) 仅打开串口、不主动改 RTS/DTR，监听几秒（验证“打开串口本身”的影响）\n"
        "  1) RTS/DTR 扫描 + 手动记录 LED 行为\n"
        "  2) 强制进入下载模式 + 监听 bootloader 日志\n"
        "  3) 空闲状态监听应用日志（不主动拉下载，你可手动复位板子）\n"
        "  4) 打开串口监听，同时执行一次 esptool 命令\n"
        "  5) 先监听，再触发进入下载模式，然后运行一次 esptool\n"
    )
    try:
        mode = input("请输入模式编号 (0/1/2/3/4/5，默认 1): ").strip() or "1"
    except EOFError:
        mode = "1"

    # 通用的监听线程工厂
    def start_listener():
        nonlocal ser
        stop_flag = {"stop": False}
        buf = {"data": ""}

        def listen():
            while not stop_flag["stop"]:
                try:
                    if ser.in_waiting:
                        data = ser.read(ser.in_waiting)
                        if not data:
                            time.sleep(0.01)
                            continue
                        buf["data"] += data.decode("utf-8", errors="ignore")
                except Exception:
                    time.sleep(0.05)
                time.sleep(0.01)

        t = threading.Thread(target=listen, daemon=True)
        t.start()
        return stop_flag, buf, t

    # 模式 0：仅打开串口，不改 RTS/DTR，监听几秒
    if mode == "0":
        print("\n[模式 0] 仅打开串口，不主动修改 RTS/DTR，监听几秒")
        stop_listening, buffer_box, listener = start_listener()

        duration = 5
        print(
            f"\n步骤2: 保持当前驱动默认的 RTS/DTR 状态，只监听 {duration} 秒。\n"
            "你可以此时观察：刚打开串口这一段时间内，LED 是否发生变化、串口是否打印 boot/下载日志。"
        )
        for i in range(duration, 0, -1):
            print(f"  剩余 {i} 秒...", end="\r", flush=True)
            time.sleep(1)
        print()

        stop_listening["stop"] = True
        listener.join(timeout=1)

        buffer = buffer_box["data"]
        print("\n监听结束。")
        print(f"监听缓冲区长度: {len(buffer)} 字符")
        if buffer:
            print("===== 串口输出开始 =====")
            print(buffer)
            print("===== 串口输出结束 =====")
        else:
            print("未收到任何数据（可能一直处于复位，或波特率/连接不匹配）。")

    # 模式 1：RTS/DTR 扫描（原来的功能）
    elif mode == "1":
        print("\n[模式 1] RTS/DTR 扫描 + 手动记录 LED 行为")
        stop_listening, buffer_box, listener = start_listener()

        print("\n步骤2: 依次切换几种 RTS/DTR 组合，请盯着板子的 LED 看变化，并在每种模式后用数字反馈。")
        print("说明：True/False 是 pyserial 层面的布尔值，实际电平可能和 MCU 端是反相连接。")
        print(
            "推荐约定：0=无明显变化，1=LED 熄灭，2=LED 重新点亮/复位，3=进入下载/异常闪烁，其他=你想补充的描述。\n"
        )

        patterns = [
            # (描述, rts, dtr)
            ("模式 0: 空闲参考状态 (RTS=False, DTR=False)", False, False),
            ("模式 1: 仅 RTS=True  (DTR=False)", True, False),
            ("模式 2: 仅 DTR=True  (RTS=False)", False, True),
            ("模式 3: RTS=True,  DTR=True", True, True),
            ("模式 4: RTS=False, DTR=True", False, True),
            ("模式 5: RTS=True,  DTR=False (再测一次)", True, False),
        ]

        observations: list[tuple[int, str, str]] = []

        try:
            for idx, (desc, rts_val, dtr_val) in enumerate(patterns):
                print(f"\n=== {desc} (index={idx}) ===")
                ser.rts = rts_val
                ser.dtr = dtr_val
                print(f"  已设置: RTS={ser.rts}, DTR={ser.dtr}")
                print("  → 请此时观察 LED：是否熄灭 / 重新点亮 / 进入异常状态？")
                time.sleep(1.0)

                try:
                    user_input = input(
                        "  请用一个数字/短语描述当前 LED 行为 "
                        "(建议: 0=无变化,1=熄灭,2=重新点亮/复位,3=异常/下载模式, 其他=自定义): "
                    ).strip()
                except EOFError:
                    user_input = ""

                if not user_input:
                    user_input = "未填写"

                observations.append((idx, desc, user_input))
        except Exception as e:
            print(f"✗ 在切换 RTS/DTR 组合时出错: {e}")

        print("\n步骤3: 结束测试，停止监听。")
        stop_listening["stop"] = True
        listener.join(timeout=1)

        buffer = buffer_box["data"]
        print("\n监听结束。")
        print(f"监听缓冲区长度: {len(buffer)} 字符")
        if buffer:
            print("===== 串口输出开始 =====")
            print(buffer)
            print("===== 串口输出结束 =====")
        else:
            print("未收到任何数据（可能一直处于复位，或波特率/连接不匹配）。")

        print("\n===== 你的 LED 行为反馈汇总 =====")
        if observations:
            for idx, desc, obs in observations:
                print(f"[index={idx}] {desc} -> 你的反馈: {obs}")
        else:
            print("（没有记录到任何反馈）")

    # 模式 2：强制进入下载模式 + 监听 bootloader 日志
    elif mode == "2":
        print("\n[模式 2] 强制进入下载模式 + 监听 bootloader 日志")
        stop_listening, buffer_box, listener = start_listener()

        print("\n步骤2: 将芯片拉到 DOWNLOAD(UART0) 状态（类似 esptool 下载前的状态）...")
        try:
            # 根据前面的实验，任一 RTS/DTR=True 都会进入下载模式，这里选用 RTS=True, DTR=False
            ser.rts = True
            ser.dtr = False
            print(f"已设置: RTS={ser.rts}, DTR={ser.dtr} （预期进入 DOWNLOAD 模式）")
        except Exception as e:
            print(f"✗ 设置 RTS/DTR 时出错: {e}")

        duration = 5
        print(f"\n步骤3: 在下载模式下监听 {duration} 秒，你可以观察串口日志和 LED 行为。")
        for i in range(duration, 0, -1):
            print(f"  剩余 {i} 秒...", end="\r", flush=True)
            time.sleep(1)
        print()

        stop_listening["stop"] = True
        listener.join(timeout=1)

        buffer = buffer_box["data"]
        print("\n监听结束。")
        print(f"监听缓冲区长度: {len(buffer)} 字符")
        if buffer:
            print("===== 串口输出开始 =====")
            print(buffer)
            print("===== 串口输出结束 =====")
        else:
            print("未收到任何数据（可能一直处于复位，或波特率/连接不匹配）。")

    # 模式 3：空闲状态监听应用日志
    elif mode == "3":
        print("\n[模式 3] 空闲状态监听应用日志（不主动拉下载）")
        stop_listening, buffer_box, listener = start_listener()

        try:
            ser.rts = False
            ser.dtr = False
            print(f"\n步骤2: 将 RTS/DTR 都释放为 False，尽量不干预板子启动。")
            print(f"当前 RTS={ser.rts}, DTR={ser.dtr}")
        except Exception as e:
            print(f"✗ 设置 RTS/DTR 时出错: {e}")

        duration = 5
        print(
            f"\n步骤3: 空闲状态监听 {duration} 秒。\n"
            "你可以在这段时间内手动按板子上的复位键，观察正常启动时的应用日志和 LED 行为。"
        )
        for i in range(duration, 0, -1):
            print(f"  剩余 {i} 秒...", end="\r", flush=True)
            time.sleep(1)
        print()

        stop_listening["stop"] = True
        listener.join(timeout=1)

        buffer = buffer_box["data"]
        print("\n监听结束。")
        print(f"监听缓冲区长度: {len(buffer)} 字符")
        if buffer:
            print("===== 串口输出开始 =====")
            print(buffer)
            print("===== 串口输出结束 =====")
        else:
            print("未收到任何数据（可能一直处于复位，或波特率/连接不匹配）。")

    # 模式 4：打开串口并监听，同时执行一次 esptool 命令（不复位，不进下载，预期失败）
    elif mode == "4":
        print("\n[模式 4] 打开串口并监听，同时执行一次 esptool 命令（不复位，不进下载）")
        stop_listening, buffer_box, listener = start_listener()

        # 为了避免 esptool 自己去拉 RTS/DTR 导致进入下载模式，这里显式要求它「不在前后复位」。
        # 注意：这样很可能无法成功连接到芯片，但正好可以验证「不会被强制拉进下载模式」。
        print(
            "\n步骤2: 在当前监听状态下运行 esptool（使用 --before no_reset --after no_reset，避免强制复位/进下载）。\n"
            "提示：这样 esptool 很可能报错连接失败，这是预期的；我们关心的是这期间 LED 和串口日志是否保持在应用状态。"
        )

        esptool_cmd = [
            "esptool",
            "--port",
            PORT,
            "--before",
            "no_reset",
            "--after",
            "no_reset",
            "chip_id",
        ]

        print(f"将执行命令: {' '.join(esptool_cmd)}")
        try:
            result = subprocess.run(
                esptool_cmd,
                capture_output=True,
                text=True,
                timeout=15,
            )
            print("\n===== esptool 运行结果 =====")
            print(f"返回码: {result.returncode}")
            if result.stdout:
                print("--- STDOUT ---")
                print(result.stdout)
            if result.stderr:
                print("--- STDERR ---")
                print(result.stderr)
        except subprocess.TimeoutExpired:
            print("\n✗ esptool 运行超时（超过 15 秒）。")
        except FileNotFoundError:
            print("\n✗ 未找到 esptool 命令，请确认已在当前环境中安装并可执行。")
        except Exception as e:
            print(f"\n✗ 运行 esptool 时发生异常: {e}")

        # 停止监听并输出整个过程中捕获到的串口数据
        stop_listening["stop"] = True
        listener.join(timeout=1)

        buffer = buffer_box["data"]
        print("\n===== esptool 运行期间的串口监听数据 =====")
        print(f"监听缓冲区长度: {len(buffer)} 字符")
        if buffer:
            print("===== 串口输出开始 =====")
            print(buffer)
            print("===== 串口输出结束 =====")
        else:
            print("在 esptool 运行期间未收到任何串口数据。")

    # 模式 5：先监听，再触发进入下载模式，然后在该状态下运行 esptool
    else:
        print("\n[模式 5] 先监听，再触发进入下载模式，然后在该状态下运行 esptool")
        stop_listening, buffer_box, listener = start_listener()

        print(
            "\n步骤2: 先在当前应用运行状态下监听几秒，你可以确认此时 LED 正常闪烁、无 DOWNLOAD 日志。"
        )
        for i in range(3, 0, -1):
            print(f"  预监听剩余 {i} 秒...", end="\r", flush=True)
            time.sleep(1)
        print()

        # 触发进入下载模式：根据之前实验，简单地拉 RTS=True, DTR=False 即可进入 DOWNLOAD(UART0)
        try:
            print("\n步骤3: 通过 RTS/DTR 主动触发进入下载模式 (DOWNLOAD(UART0)) ...")
            ser.rts = True
            ser.dtr = False
            print(f"  已设置: RTS={ser.rts}, DTR={ser.dtr} （预期进入 DOWNLOAD 模式）")
            # 给芯片一点时间完成复位并进入 bootloader
            time.sleep(0.3)
        except Exception as e:
            print(f"✗ 设置 RTS/DTR 时出错: {e}")

        # 在下载模式下再监听一小会儿，捕获 ROM boot 日志
        for i in range(2, 0, -1):
            print(f"  DOWNLOAD 模式下额外监听 {i} 秒...", end="\r", flush=True)
            time.sleep(1)
        print()

        print("\n步骤4: 在已经处于下载模式的前提下，运行 esptool（使用 no_reset，不再额外复位）。")

        esptool_cmd = [
            "esptool",
            "--port",
            PORT,
            "--before",
            "no_reset",
            "--after",
            "no_reset",
            "chip_id",
        ]

        print(f"将执行命令: {' '.join(esptool_cmd)}")
        try:
            result = subprocess.run(
                esptool_cmd,
                capture_output=True,
                text=True,
                timeout=15,
            )
            print("\n===== esptool 运行结果 =====")
            print(f"返回码: {result.returncode}")
            if result.stdout:
                print("--- STDOUT ---")
                print(result.stdout)
            if result.stderr:
                print("--- STDERR ---")
                print(result.stderr)
        except subprocess.TimeoutExpired:
            print("\n✗ esptool 运行超时（超过 15 秒）。")
        except FileNotFoundError:
            print("\n✗ 未找到 esptool 命令，请确认已在当前环境中安装并可执行。")
        except Exception as e:
            print(f"\n✗ 运行 esptool 时发生异常: {e}")

        # 不修改 RTS/DTR，不做退出下载的动作，让你自己决定后续（比如关闭脚本或改回 False/False）
        print(
            "\n注意：当前仍保持在触发下载时的 RTS/DTR 状态（通常是 DOWNLOAD 模式），\n"
            "你可以根据需要决定是直接关闭脚本（串口关闭后板子会重启应用），\n"
            "还是后面再用模式 3/0 等方式回到正常应用监听。"
        )

        # 停止监听并输出整个过程中捕获到的串口数据
        stop_listening["stop"] = True
        listener.join(timeout=1)

        buffer = buffer_box["data"]
        print("\n===== 整个过程中捕获到的串口监听数据 =====")
        print(f"监听缓冲区长度: {len(buffer)} 字符")
        if buffer:
            print("===== 串口输出开始 =====")
            print(buffer)
            print("===== 串口输出结束 =====")
        else:
            print("在本次流程中未收到任何串口数据。")

    # 清理前，让你观察“释放串口”的效果
    try:
        input(
            "\n现在串口仍然打开，保持在刚才模式的 RTS/DTR 组合。\n"
            "请此时再看一眼 LED 行为。确认好之后，按回车关闭串口并释放 RTS/DTR → 观察此刻 LED 是否再次变化..."
        )
    except EOFError:
        pass

    ser.close()
    print("\n✓ 测试完成，你可以根据上面的日志 + LED 行为（包括关闭串口那一刻）来判断复位/启动状态。")


if __name__ == "__main__":
    main()
