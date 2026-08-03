import pyvisa
import time

rm = pyvisa.ResourceManager()

scope = rm.open_resource("TCPIP0::10.59.26.43::INSTR")


# Apply settings for large binary streaming
scope.timeout = 5000       # 5 seconds to ensure it doesn't time out mid-stream
scope.chunk_size = 1000000 # 1 MB buffer chunk size to grab the entire image cleanly

# Clear old traffic from the interface buffer
scope.clear()
time.sleep(0.5)

try:
    print("Step 1: Sending 'SCDP' Write operation...")
    scope.write('SCDP')
    
    # Give the scope hardware a brief moment to process the request
    time.sleep(0.5) 
    
    print("Step 2: Performing Read operation...")
    # This matches the raw Read button you clicked in NI MAX
    screen_data = scope.read_raw()
    
    # 3. Check for the bitmap header signature and write to file
    if screen_data.startswith(b'BM'):
        output_path = 'pictures/fall_time_square.bmp'
        with open(output_path, 'wb') as f:
            f.write(screen_data)
        print(f"Success! Captured {len(screen_data)} bytes. File saved as '{output_path}'.")
    else:
        print("Data grabbed, but header did not match standard BMP format.")
        print(f"First few bytes look like: {screen_data[:15]}")

except pyvisa.errors.VisaIOError as e:
    print(f"Visa IO Error during transfer: {e}")

finally:
    scope.close()