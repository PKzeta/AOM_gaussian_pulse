import pyvisa
import time
import csv

# --- CONFIGURATION ---
CH_NUMBER = 'C1'  # Change to 'C2' for Channel 2
OUTPUT_CSV = 'scope_data\c_gauss\gauss1.8csv'

rm = pyvisa.ResourceManager()

scope = rm.open_resource("TCPIP0::10.59.26.43::INSTR")
scope.timeout = 5000
scope.chunk_size = 1000000
scope.clear()
time.sleep(0.5)

try:
    # 1. Query scaling factors and clean strings thoroughly
    # .strip().lower() handles unexpected spaces and mixed-case units (like 's' vs 'S')
    vdiv_raw = scope.query(f'{CH_NUMBER}:VDIV?').split()[-1].strip().lower()
    vdiv = float(vdiv_raw.replace('v', ''))
    
    voffset_raw = scope.query(f'{CH_NUMBER}:OFST?').split()[-1].strip().lower()
    voffset = float(voffset_raw.replace('v', ''))
    
    sdiv_raw = scope.query('TDIV?').split()[-1].strip().lower()
    sdiv = float(sdiv_raw.replace('s', ''))
    
    print(f"Scale Factors -> Volt/Div: {vdiv}V, Offset: {voffset}V, Time/Div: {sdiv}s")


    # 2. Request the raw waveform data points
    # Separating Write and Read to prevent protocol crashes
    scope.write(f'{CH_NUMBER}:WF? DAT2')
    time.sleep(0.5)
    raw_packet = scope.read_raw()

    # 3. Clean up the packet header
    # Siglent headers look like: "C1:WF DAT2,#9000004000..." 
    # We find where the raw data block starts by locating the '#' sign
    header_end = raw_packet.find(b'#')
    if header_end == -1:
        raise ValueError("Could not find the data block header in the scope's response.")
    
    # The character after '#' tells us how many digits specify the length (usually '9')
    length_digits = int(chr(raw_packet[header_end + 1]))
    data_start_index = header_end + 2 + length_digits
    
    # Extract the raw ADC byte data (stripping the trailing \n\n usually sent at the end)
    raw_data = raw_packet[data_start_index:-2]
    
    print(f"Successfully extracted {len(raw_data)} data points.")

    # 4. Convert raw bytes into Time and Voltage coordinates
    # Grid math: Siglent screens usually have 14 horizontal divs and 8 vertical divs
    total_time = sdiv * 14 
    time_step = total_time / len(raw_data)
    
    csv_rows = [['Time (s)', 'Voltage (V)']]
    
    for i, raw_byte in enumerate(raw_data):
        # Convert unsigned byte (0 to 255) to signed integer (-128 to 127)
        signed_pixel = raw_byte - 256 if raw_byte > 127 else raw_byte
        
        # Calculate real voltage and time positions
        voltage = signed_pixel * (vdiv / 25) - voffset
        timestamp = (i * time_step) - (total_time / 2) # Center around 0 seconds
        
        csv_rows.append([timestamp, voltage])

    # 5. Save to CSV
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
