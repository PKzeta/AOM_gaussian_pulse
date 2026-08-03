import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from scipy import optimize


def linear_func(x, m, b):
    return m * x + b


def crossing_time(x, y, level, i0, i1, rising=True):
    """
    Find the time where signal crosses a threshold.
    Uses linear interpolation between samples.
    """
    seg_y = y[i0:i1]
    seg_x = x[i0:i1]

    if rising:
        idx = np.where(seg_y >= level)[0]
    else:
        idx = np.where(seg_y <= level)[0]

    if len(idx) == 0:
        return None

    k = idx[0]

    if k == 0:
        return seg_x[0]

    x0, x1 = seg_x[k-1], seg_x[k]
    y0, y1 = seg_y[k-1], seg_y[k]

    if y1 == y0:
        return x1

    frac = (level - y0)/(y1-y0)

    return x0 + frac*(x1-x0)



if __name__ == "__main__":

    measured_widths = []

    # these are your programmed square flat-top durations
    widths = np.array([
        0.3, 0.4, 0.5, 0.6, 0.7,
        0.8, 0.9, 1.0, 1.25
    ])

    for i in widths:

        filename = f"scope_data/square_data/square_data/square{i}.csv"

        df = pd.read_csv(
            filename,
            header=None,
            usecols=[0,1],
            skiprows=100,
            nrows=50000
        )

        x = df.iloc[:,0].to_numpy()
        y = df.iloc[:,1].to_numpy()


        # Find baseline and peak
        baseline = np.mean(y[:])

        max_index = np.argmax(y)
        peak = y[max_index]


        # 50% threshold
        threshold = baseline + 0.5*(peak-baseline)


        # Search around pulse
        start = max(0, max_index-1000)
        end = min(len(y), max_index+1000)


        # rising edge
        t_rise = crossing_time(
            x,
            y,
            threshold,
            start,
            max_index,
            rising=True
        )


        # falling edge
        t_fall = crossing_time(
            x,
            y,
            threshold,
            max_index,
            end,
            rising=False
        )


        if t_rise is None or t_fall is None:
            print(f"failed for {i} us")
            continue


        width = (t_fall - t_rise)*1e6  # seconds -> us

        measured_widths.append(width)


        # Plot each pulse
        plot_pulse = True

        if plot_pulse:

            plt.figure()

            plt.plot(
                x[start:end],
                y[start:end],
                label="photodiode signal"
            )

            plt.axhline(
                threshold,
                linestyle="--",
                label="100% threshold"
            )

            plt.axvline(
                t_rise,
                linestyle=":"
            )

            plt.axvline(
                t_fall,
                linestyle=":"
            )


            plt.xlabel("Time (s)")
            plt.ylabel("Voltage (V)")
            plt.title(
                f"Square pulse {i} us\nMeasured width = {width:.3f} us"
            )

            plt.grid(True)
            plt.legend()
            plt.show()



    measured_widths = np.array(measured_widths)



    # Compare programmed vs measured
    popt, _ = optimize.curve_fit(
        linear_func,
        widths[1:],
        measured_widths[1:]
    )


    plt.figure()

    plt.plot(
        widths,
        measured_widths,
        marker='x',
        linestyle='',
        label="Measured"
    )


    plt.plot(
        widths[0:],
        linear_func(widths[0:], *popt),
        label="Linear fit"
    )


    plt.xlabel("Programmed Flat-top Duration (us)")
    plt.ylabel("Measured Pulse Width (us)")
    plt.title("Square Pulse Width Calibration")

    plt.legend(
        [f"Linear fit: y={popt[0]:.3f}x+{popt[1]:.3f}"],
        loc="upper left"
    )

    plt.grid(True)
    plt.savefig('scope_data/square_data/square_data/signal_difference_square.png', dpi = 300)

    plt.show()