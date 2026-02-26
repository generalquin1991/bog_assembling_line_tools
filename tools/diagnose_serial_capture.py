#!/usr/bin/env python3
"""诊断脚本：验证串口数据捕获的完整性和时序"""
import serial
import time
import sys
import threading
from collections import deque

PORT = sys.argv[1] if len(sys.argv) > 1 else '/dev/cu.wchusbserial110'
BAUD = 78400

print(f"诊断串口: {PORT}")
print(f"波特率: {BAUD}\n")

# 全局变量
ser = None
stop_reading = False
all_data = bytearray()
total_bytes = 0
read_count = 0

def wait_for_enter(prompt):
    """等待用户按回车确认"""
    input(f"{prompt} (按回车继续...)")

def print_rts_dtr_status(ser_obj=None):
    """打印当前RTS和DTR状态"""
    if ser_obj is None:
        print("  [状态] 串口未打开，无法获取RTS/DTR状态")
        return
    
    try:
        dtr = ser_obj.dtr
        rts = ser_obj.rts
        print(f"  [状态] DTR={dtr}, RTS={rts}")
    except Exception as e:
        print(f"  [状态] 无法获取RTS/DTR状态: {e}")

def read_thread():
    """专用读取线程：持续读取串口数据，实时打印"""
    global stop_reading, all_data, total_bytes, read_count, ser
    import sys
    
    while not stop_reading:
        try:
            if ser is not None and ser.is_open:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting)
                    if data:
                        all_data.extend(data)
                        total_bytes += len(data)
                        read_count += 1
                        
                        # 实时显示接收到的数据（立即刷新输出）
                        try:
                            text = data.decode('utf-8', errors='replace')
                            # 直接打印文本，立即刷新
                            print(text, end='', flush=True)
                        except:
                            # 二进制数据，以十六进制显示
                            hex_str = ' '.join(f'{b:02x}' for b in data[:50])
                            print(f"\n[二进制数据 {len(data)}B] {hex_str}", flush=True)
                            if len(data) > 50:
                                print(f"  ... (还有 {len(data) - 50} 字节)", flush=True)
            # 使用极小的延迟，最大化读取频率
            time.sleep(0.0001)  # 0.1ms延迟，最大化读取频率
        except Exception as e:
            if not stop_reading:
                print(f"\n[错误] 读取异常: {e}", flush=True)
            time.sleep(0.1)

# 主流程
print("="*80)
print("串口RTS/DTR状态测试流程")
print("="*80)
print("\n正确的复位流程说明（根据当前实测现象矫正）：")
print("  RTS 控制复位信号（DTR保持原状，不修改）：")
print("    - RTS=True  -> 设备进入复位状态（停止运行）")
print("    - RTS=False -> 设备退出复位状态（正常运行）")
print("  复位流程（推荐时序）：")
print("  1. 拉低 RTS (RTS=False)  -> 确保设备处于运行状态")
print("  2. 拉高 RTS (RTS=True)   -> 设备进入复位状态")
print("  3. 保持高电平 100ms      -> 复位保持时间")
print("  4. 再次拉低 RTS (RTS=False) -> 设备退出复位并重新启动，输出 bootloader 日志")
print("  注意：本测试只修改 RTS，DTR 只作为观察对象，不做修改")
print("="*80)

# 步骤1: 打印当前RTS,DTR状态（串口未打开）
print("\n步骤1: 打印当前RTS/DTR状态（串口未打开）")
print_rts_dtr_status()
wait_for_enter("准备打开串口")

# 步骤2: 开启串口监听
print("\n步骤2: 开启串口监听")
print("  → 打开串口...")
wait_for_enter("准备打开串口")
ser = serial.Serial(
    PORT, 
    BAUD, 
    timeout=0.1,
    dsrdtr=False,  # 禁用 DSR/DTR 自动流控
    rtscts=False   # 禁用 RTS/CTS 自动流控
)
print(f"  ✓ 串口已打开: {PORT}")
wait_for_enter("串口已打开")

# 清空可能存在的残留数据
print("  → 清空可能存在的残留数据...")
wait_for_enter("准备清空残留数据")
if ser.in_waiting > 0:
    leftover = ser.read(ser.in_waiting)
    print(f"  ✓ 已清空残留数据: {len(leftover)} 字节")
else:
    print("  ✓ 无残留数据")
wait_for_enter("残留数据已清空")

# 启动读取线程
print("  → 启动读取线程...")
wait_for_enter("准备启动读取线程")
reader = threading.Thread(target=read_thread, daemon=True)
reader.start()
time.sleep(0.1)  # 等待线程启动
print("  ✓ 读取线程已启动")
print("  → 串口数据将实时打印（任何时刻收到数据都会立即显示）")
wait_for_enter("读取线程已启动")

# 步骤3: 打印当前RTS,DTR状态（串口已打开）
print("\n步骤3: 打印当前RTS/DTR状态（串口已打开）")
print_rts_dtr_status(ser)
print("  ℹ️  注意：本测试只修改RTS，DTR保持当前状态不变")
wait_for_enter("准备设置RTS为运行状态（DTR不修改）")

# 步骤4: 拉低RTS（确保设备处于运行状态）
print("\n步骤4: 拉低RTS（确保设备处于运行状态）")
print("  → RTS=False: 设备退出复位状态（正常运行）")
print("  → DTR: 保持当前状态不变（不修改）")
wait_for_enter("准备拉低RTS")
ser.rts = False  # RTS=False: 设备退出复位，正常运行
ser.flush()
time.sleep(0.01)  # 短暂延迟确保信号稳定
print(f"  ✓ 已设置 RTS=False（DTR保持为 {ser.dtr}，未修改）")
print("  ✓ 设备应处于正常运行状态")
wait_for_enter("RTS已拉低，设备应正常运行")

# 步骤5: 打印当前RTS,DTR状态（拉低后）
print("\n步骤5: 打印当前RTS/DTR状态（拉低后）")
print_rts_dtr_status(ser)
print("  ℹ️  当前状态：RTS=False -> 设备应处于正常运行状态")
wait_for_enter("准备拉高RTS（进入复位状态）")

# 步骤6: 拉高RTS, 100ms（进入复位状态）
print("\n步骤6: 拉高RTS，保持100ms（进入复位状态）")
print("  → RTS=True: 设备进入复位状态（停止运行）")
wait_for_enter("准备拉高RTS进入复位状态")
print("  → 拉高RTS（设备将进入复位状态，停止运行）...")
ser.rts = True  # RTS=True: 设备进入复位状态
ser.flush()
print("  ✓ 已设置 RTS=True（设备已进入复位状态，停止运行）")
wait_for_enter("RTS已拉高，设备已进入复位状态")
print("  → 等待100ms（复位高电平期间，读取线程持续读取）...")
wait_for_enter("准备等待100ms")
time.sleep(0.1)  # 100ms
print("  ✓ 100ms已过（复位高电平期间结束）")
wait_for_enter("100ms等待完成，设备仍处于复位状态")

# 步骤7: 打印当前RTS,DTR状态（拉高RTS后）
print("\n步骤7: 打印当前RTS/DTR状态（拉高RTS后）")
print_rts_dtr_status(ser)
print("  ℹ️  当前状态：RTS=True -> 设备处于复位状态（停止运行）")
wait_for_enter("准备拉低RTS（退出复位状态，设备将重新启动）")

# 步骤8: 拉低RTS（退出复位状态，设备重新启动）
print("\n步骤8: 拉低RTS（退出复位状态，设备将重新启动）")
print("  → RTS=False: 设备退出复位状态（重新启动）")
wait_for_enter("准备拉低RTS退出复位状态")
print("  → 拉低RTS（设备将退出复位状态，重新启动）...")
ser.rts = False  # RTS=False: 设备退出复位状态
ser.flush()
time.sleep(0.01)  # 短暂延迟确保信号稳定
print("  ✓ 已设置 RTS=False（设备已退出复位状态）")
wait_for_enter("RTS已拉低，设备已退出复位状态")
print("  → 设备应该开始重新启动，bootloader日志应该开始输出...")
print("  → 等待2秒，观察设备启动日志...")
wait_for_enter("准备等待2秒观察设备启动")
time.sleep(2.0)  # 等待设备启动并输出bootloader日志
print("  ✓ 等待完成")
wait_for_enter("设备应已重新启动")

# 步骤9: 打印当前RTS,DTR状态（退出复位后）
print("\n步骤9: 打印当前RTS/DTR状态（退出复位后）")
print_rts_dtr_status(ser)
print("  ℹ️  当前状态：RTS=False -> 设备应处于正常运行状态")
wait_for_enter("准备关闭串口监听")

# 步骤10: 关闭串口监听
print("\n步骤10: 关闭串口监听")
print("  → 停止读取线程...")
wait_for_enter("准备停止读取线程")
stop_reading = True
time.sleep(0.2)  # 等待线程停止
print("  ✓ 读取线程已停止")
wait_for_enter("读取线程已停止")
print("  → 关闭串口...")
wait_for_enter("准备关闭串口")
ser.close()
print("  ✓ 串口已关闭")
wait_for_enter("串口已关闭")

# 步骤11: 打印当前RTS,DTR状态（串口已关闭）
print("\n步骤11: 打印当前RTS/DTR状态（串口已关闭）")
print_rts_dtr_status(ser)
wait_for_enter("准备查看统计信息")

# 统计信息
print("\n" + "="*80)
print("统计信息")
print("="*80)
print(f"总读取次数: {read_count}")
print(f"总数据量: {total_bytes} 字节")
if all_data:
    try:
        text = all_data.decode('utf-8', errors='ignore')
        print(f"总字符数: {len(text)}")
        print(f"\n接收到的数据预览（前500字符）:")
        print("-" * 80)
        print(text[:500])
        if len(text) > 500:
            print(f"\n... (还有 {len(text) - 500} 字符)")
    except Exception as e:
        print(f"解码错误: {e}")
        print(f"原始数据: {all_data[:100]}")
else:
    print("未接收到任何数据")

print("\n" + "="*80)
print("测试完成")
print("="*80)
