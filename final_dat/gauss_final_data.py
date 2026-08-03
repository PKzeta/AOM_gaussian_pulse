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
        
    std_photodiode = []
    widths = np.array([0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0])

    for i in widths:
        filename = f"final_dat/gauss{i}.csv"
        df = pd.read_csv(
        filename,
        header=None,
        usecols=[0, 1],   
        skiprows=50,       
        nrows=5000000      
    )

        x = df.iloc[:, 0]
        y = df.iloc[:, 1]
        
        max_index = np.argmax(y)
        
        start = max(0, max_index - 800)
        end = min(len(y), max_index + 800)
            
        x_fit = x.iloc[start:end]
        y_fit = y.iloc[start:end]

        popt, _ = optimize.curve_fit(
            gaussian,
            x_fit,
            y_fit,
            p0=[y.max(), x.iloc[max_index], i * 1e-6 *0.8, 0]
        )
        
        std_photodiode.append(popt[2] * 1e6)  # Convert to microseconds
        plot_gauss = True
        if plot_gauss == True: 
            plt.figure()
            plt.xlabel("Time (s)")
            plt.ylabel("Voltage (V)")
            plt.title(f"{i}us gaussian sigma")
            plt.grid(True)
            # plt.plot(x, y) #if want to see full
            # plt.plot(x, gaussian(x, *popt))
            plt.plot(x_fit, y_fit, label="Data")
            plt.plot(x_fit, gaussian(x_fit, *popt), label="Gaussian fit")
            plt.legend([f"standard deviation (us) = {popt[2]*1e6:.2e}"], loc="upper right")
            plt.savefig("gaussian_fit.png", dpi=300)
            # plt.show()

        plot_residuals = True
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
            std_photodiode = np.asarray(std_photodiode)
            mask = widths != 1
            popt, _ = optimize.curve_fit(linear_func, widths[mask], std_photodiode[mask])
            plt.figure()
            plt.plot(widths, std_photodiode, marker='x', linestyle='', label="Data")
            plt.plot(widths, linear_func(widths, *popt), label="Linear fit")
            # plt.xscale('log')
            # plt.yscale('log')
            plt.xlabel("Input Pulse Width (us)")
            plt.ylabel("Standard Deviation of Photodiode Signal (us)")
            plt.title("Standard Deviation of Photodiode Signal vs Input Pulse Width")
            plt.legend([f"Linear fit: y = {popt[0]:.2f}x + {popt[1]:.2f}"], loc="upper left")
            plt.savefig('gaussian_data_expected.png', dpi = 300)
            plt.show()
