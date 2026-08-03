import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import curve_fit


def saw_rise_envelope(t_us, sigma_us, n_sigma=4):

    edge = n_sigma * sigma_us

    env = np.zeros_like(t_us)

    idx = (t_us >= -edge) & (t_us <= 0)

    env[idx] = (t_us[idx] + edge) / edge

    return env


def fit_model(t_us, A, B, t0, sigma_us):

    return B + A * saw_rise_envelope(
        t_us - t0,
        sigma_us,
        n_sigma=4
    )


if __name__ == "__main__":

    sigma_values = np.array(
        [0.01,0.1,0.2,0.3,0.4,0.5,
         0.6,0.7,0.8,0.9,1.0,1.25]
    )

    measured_sigma = []

    for i in sigma_values:

        filename = f"scope_data/saw/saw{i}.csv"

        df = pd.read_csv(
            filename,
            header=None,
            usecols=[0,1],
            skiprows=100,
            nrows=5000
        )

        x = df.iloc[:,0].to_numpy()
        y = df.iloc[:,1].to_numpy()

        # convert seconds -> microseconds
        x_us = x * 1e6


        # roughly isolate rising edge
        baseline = np.median(y[:100])
        peak = np.max(y)

        start = np.argmax(y > baseline + 0.05*(peak-baseline))-50
        end = start + 500

        start=max(start,0)
        end=min(end,len(y))

        xf = x_us[start:end]
        yf = y[start:end]


        # initial guesses
        A0 = peak-baseline
        B0 = baseline
        t00 = xf[np.argmax(yf > baseline+0.5*A0)]

        p0 = [
            A0,
            B0,
            t00,
            i
        ]


        popt, pcov = curve_fit(
            fit_model,
            xf,
            yf,
            p0=p0
        )


        A_fit, B_fit, t0_fit, sigma_fit = popt

        measured_sigma.append(sigma_fit)
        plt.xlabel("Time (s)")
        plt.ylabel("Voltage (V)")
        plt.title(
            f"Square pulse {i} us\nramp width = {i:.3f} us"
            )

        plt.figure()
        plt.plot(xf,yf,label="photodiode")
        plt.plot(
            xf,
            fit_model(xf,*popt),
            label=f"fit sigma={sigma_fit:.4f} us"
        )
        plt.xlabel("time (us)")
        plt.ylabel("voltage")
        plt.grid()
        plt.legend()


    plt.show()


    measured_sigma=np.array(measured_sigma)


    plt.figure()
    plt.plot(
        sigma_values,
        measured_sigma,
        'x',
        label="measured"
    )

    p=np.polyfit(
        sigma_values,
        measured_sigma,
        1
    )

    plt.plot(
        sigma_values,
        np.polyval(p,sigma_values),
        label=f"slope={p[0]:.3f}"
    )

    plt.xlabel("programmed sigma (us)")
    plt.ylabel("fitted sigma (us)")
    plt.grid()
    plt.legend()
    plt.show()