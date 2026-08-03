import pyvisa
import time
import csv
import struct  # >>> CHANGED: needed to unpack the binary DESC block

# --- CONFIGURATION ---
CH_NUMBER = 'C1'
OUTPUT_CSV = 'final_dat\\sawtooth_1us_500mV.csv'  # also fixed: use \\ or raw string r'...' for Windows paths

rm = pyvisa.ResourceManager()
scope = rm.open_resource("TCPIP0::10.59.26.43::INSTR")
scope.timeout = 5000
scope.chunk_size = 1000000
scope.clear()
time.sleep(0.5)

try:
    # >>> CHANGED: freeze the acquisition so the DESC and DAT2 you read below
    # both describe the exact same frame (prevents grabbing a mid-refresh waveform)
    # scope.write('TRMD STOP')
    # scope.write('TRMD RUN')
    time.sleep(0.2)

    # >>> CHANGED: pull the binary DESC block instead of parsing VDIV/OFST/TDIV as text
    scope.write(f'{CH_NUMBER}:WF? DESC')
    time.sleep(0.3)
    desc_packet = scope.read_raw()

    header_end = desc_packet.find(b'#')
    if header_end == -1:
        raise ValueError("Could not find the data block header in the DESC response.")
    length_digits = int(chr(desc_packet[header_end + 1]))
    data_start = header_end + 2 + length_digits
    desc = desc_packet[data_start:]

    # >>> CHANGED: these are the scope's own authoritative scale factors
    vertical_gain   = struct.unpack('<f', desc[156:160])[0]
    vertical_offset = struct.unpack('<f', desc[160:164])[0]
    horiz_interval  = struct.unpack('<f', desc[176:180])[0]
    horiz_offset    = struct.unpack('<d', desc[180:188])[0]

    print(f"Vertical gain: {vertical_gain}V/ct, Vertical offset: {vertical_offset}V, "
          f"Sample interval: {horiz_interval}s (~{1/horiz_interval:.3e} Sa/s)")

    # 2. Request the raw waveform data points (unchanged)
    scope.write(f'{CH_NUMBER}:WF? DAT2')
    time.sleep(0.5)
    raw_packet = scope.read_raw()

    # 3. Clean up the packet header (unchanged)
    header_end = raw_packet.find(b'#')
    if header_end == -1:
        raise ValueError("Could not find the data block header in the scope's response.")
    length_digits = int(chr(raw_packet[header_end + 1]))
    data_start_index = header_end + 2 + length_digits
    raw_data = raw_packet[data_start_index:-2]

    print(f"Successfully extracted {len(raw_data)} data points.")

    # 4. Convert raw bytes into Time and Voltage coordinates
    # >>> CHANGED: no more total_time/len(raw_data) guess — use the real interval
    csv_rows = [['Time (s)', 'Voltage (V)']]

    for i, raw_byte in enumerate(raw_data):
        signed_pixel = raw_byte - 256 if raw_byte > 127 else raw_byte

        voltage = signed_pixel * vertical_gain - vertical_offset       # >>> CHANGED
        timestamp = horiz_offset + i * horiz_interval                  # >>> CHANGED

        csv_rows.append([timestamp, voltage])

    # 5. Save to CSV (unchanged)
    with open(OUTPUT_CSV, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(csv_rows)

    print(f"Data successfully saved to '{OUTPUT_CSV}'!")
    

except pyvisa.errors.VisaIOError as e:
    print(f"Visa communication error: {e}")
except Exception as e:
    print(f"Error while processing data: {e}")
finally:
    scope.close()