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
        
    amp_photodiode = []
    amplitudes = np.array([80,100,120,140, 160, 180, 200, 220, 240, 250, 260, 280, 300, 320, 340, 360, 380])

    for i in amplitudes:
        filename = f"final_dat/amp{i}.csv"
        df = pd.read_csv(
        filename,
        header=None,
        usecols=[0, 1],   
        skiprows=100,       
        nrows=5000000      
    )

        x = df.iloc[:, 0]
        y = df.iloc[:, 1]
        
        max_index = np.argmax(y)
        start = max(0, max_index - 400)
        end = min(len(y), max_index + 400)
            
        x_fit = x.iloc[start:end]
        y_fit = y.iloc[start:end]

        popt, _ = optimize.curve_fit(
            gaussian,
            x_fit,
            y_fit,
            p0=[y.max(), x.iloc[max_index], 1e-6*0.8, 0]
        )
        
        # amp_photodiode.append(popt[0] * 1e3)  # Convert to milivolts
        amp_photodiode.append(np.mean(np.partition(y_fit, -5)[-5:]))  # Use the mean of the top 10 values for amplitude
        plot_gauss = False
        if plot_gauss == True: 
            plt.figure()
            plt.xlabel("Time (s)")
            plt.ylabel("Voltage (V)")
            plt.title(f"{i} amp")
            plt.grid(True)
            #plt.plot(x, y) #if want to see full
            # plt.plot(x, gaussian(x, *popt))
            plt.plot(x_fit, y_fit, label="Data")
            plt.plot(x_fit, gaussian(x_fit, *popt), label="Gaussian fit")
            plt.legend([f"amplitude (mV) = {popt[0]*1e3:.2e}"], loc="upper right")
            plt.savefig("gaussian_ fit.png", dpi=300)
            # plt.show()

        plot_residuals = False
        if plot_residuals == True:
            residuals = (y_fit - gaussian(x_fit, *popt)) 
            plt.figure()
            plt.xlabel("Time (s)")
            plt.ylabel("Residuals (V)")
            plt.title(f"{i}us gaussian residuals")
            plt.grid(True)
            plt.plot(x_fit, residuals, label="Residuals", linestyle='', marker='.', markersize=2)
            plt.axhline(0, color='red', linestyle='--')
            plt.legend()
            # plt.savefig("gaussian_residuals.png", dpi=300)
            print(f"root mean square error (RMSE) for {i}us: {np.sqrt(np.mean(residuals**2)):.2e} V")
            print(f"peak voltage for {i}us: {y_fit.max():.2e} V")
            print("")
    plt.show()

    final_plot = True
    if final_plot == True:
            amp_photodiode = np.asarray(amp_photodiode)
            mask = amplitudes < 260 
            popt, _ = optimize.curve_fit(linear_func, amplitudes[mask], amp_photodiode[mask])
            plt.figure()
            plt.plot(amplitudes, amp_photodiode, marker='x', linestyle='', label="Data")
            plt.plot(amplitudes, linear_func(amplitudes, *popt), label="Linear fit")
            # plt.xscale('log')
            # plt.yscale('log')
            plt.xlabel("Input Pulse amplitude (us)")
            plt.ylabel("somethign amp check how done")
            plt.title("amp signal vs amp sent to aom")
            plt.legend([f"Linear fit: y = {popt[0]:.2f}x + {popt[1]:.2f}"], loc="upper left")
            plt.show()

