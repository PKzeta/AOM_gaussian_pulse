import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from scipy import optimize
# No header row in this file, and it's comma or tab separated —
# pandas usually auto-detects, but sep=None + engine='python' is safest
def gaussian(x, amplitude, mean, stddev, c):
    return amplitude * np.exp(-((x - mean)**2) / (2 * stddev**2)) + c

def linear_func(x, m, b):
        return m * x + b

if __name__ == "__main__":
        
    filename = f"final_dat\square_rise_time_1us_chan1.csv"
    df = pd.read_csv(
    filename,
    header=None,
    usecols=[0, 1],   
    skiprows=50,       
    nrows=5000000      
)
    filename = f"final_dat\square_rise_time_1us_chan2.csv"
    df2 = pd.read_csv(
    filename,
    header=None,
    usecols=[0, 1],   
    skiprows=50,       
    nrows=5000000      
)
    x = df.iloc[:, 0]
    y1 = df.iloc[:, 1]
    y2 = df2.iloc[:, 1]

    max_index = np.argmax(y2)
    
    start = max(0, max_index - 100)
    end = min(len(y1), max_index + 500)
        
    x_fit = x.iloc[start:end]
    y1_fit = y1.iloc[start:end]
    y2_fit = y2.iloc[start:end]/1000

    plt.figure()
    plt.xlabel("Time (s)")
    plt.ylabel("Voltage (V)")
    plt.grid(True)

    plt.plot(x_fit, y1_fit, label="Channel 1")
    plt.plot(x_fit, y2_fit, label="Channel 2")

    target = 0.5 / 1000 #0.5V signal generated
    idx = np.where(y2_fit >= target)[0][0]

    plt.axvline(
        x=x_fit.iloc[idx],
        color='red',
        linestyle='--',
        label='trig sent'
    )

    peak_v = np.mean(np.partition(y1_fit, -10)[-10:])
    min_v = np.mean(np.partition(y1_fit, 10)[:10])

    idx_ninety = np.where(y1_fit >= 0.9 * (peak_v - min_v))[0][0]
    plt.axvline(
        x=x_fit.iloc[idx_ninety],
        color='red',
        linestyle='--',
        label='90%'
    )

    idx_ten = np.where(y1_fit >= 0.1 * (peak_v - min_v))[0][0]
    plt.axvline(
            x=x_fit.iloc[idx_ten],
            color='red',
            linestyle='--',
            label='10%')

    rise_time = (x_fit.iloc[idx_ninety] - x_fit.iloc[idx_ten]) * 1e9
    print(f"Rise time: {rise_time:.2f} ns")

    delay_time = (x_fit.iloc[idx_ten] - x_fit.iloc[idx]) * 1e9
    print(f"Delay time: {delay_time:.2f} ns")

    plt.legend()
    plt.show()
