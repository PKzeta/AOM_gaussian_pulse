import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from scipy import optimize
from scipy.signal import find_peaks


def linear_func(x, m, b):
    return m * x + b


if __name__ == "__main__":

    # Read CSV, skip first 10 rows, no header in file
    df = pd.read_csv('final_dat/sawtooth_1us.csv', skiprows=10, header=None)
    df.columns = ['Time', 'Voltage']

    x = df['Time']
    y = df['Voltage']

    max_index = np.argmax(y)

    start = max(0, max_index - 4000)
    end = min(len(y), max_index + 8000)

    x_fit = x.iloc[start:end].to_numpy()
    y_fit = y.iloc[start:end].to_numpy()

    average_top10 = np.mean(np.partition(y_fit, -10)[-10:])

    lower_fit = 0.3 * average_top10
    upper_fit = 0.7 * average_top10

    peaks, properties = find_peaks(
        y_fit,
        prominence=0.1 * (np.max(y_fit) - np.min(y_fit)),
        distance=100
    )

    plt.figure(figsize=(8, 5))
    plt.plot(x_fit, y_fit, label="Data")
    plt.scatter(x_fit[peaks], y_fit[peaks], color="red", label="detected peaks")

    index_middle = int((peaks[1] + peaks[0]) / 2)

    # 20%-80% (well, 30%-70% per lower_fit/upper_fit) window on rise and fall
    mask_positive = (y_fit[index_middle:peaks[1]] >= lower_fit) & (y_fit[index_middle:peaks[1]] <= upper_fit)
    mask_negative = (y_fit[peaks[0]:index_middle] >= lower_fit) & (y_fit[peaks[0]:index_middle] <= upper_fit)

    x_rise = x_fit[index_middle:peaks[1]][mask_positive]
    y_rise = y_fit[index_middle:peaks[1]][mask_positive]

    x_fall = x_fit[peaks[0]:index_middle][mask_negative]
    y_fall = y_fit[peaks[0]:index_middle][mask_negative]

    popt_rise, _ = optimize.curve_fit(linear_func, x_rise, y_rise)
    popt_fall, _ = optimize.curve_fit(linear_func, x_fall, y_fall)

    plt.plot(x_fit[peaks[0]:index_middle], linear_func(x_fit[peaks[0]:index_middle], *popt_fall), label="fall fit")
    plt.plot(x_fit[index_middle:peaks[1]], linear_func(x_fit[index_middle:peaks[1]], *popt_rise), label="rise fit")

    plt.title('Voltage vs Time')
    plt.xlabel('Time')
    plt.ylabel('Voltage')
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    print("fall slope:", popt_fall[0], "rise slope:", popt_rise[0])
    plt.show()