import logging
from dataclasses import InitVar, dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import pvlib


def format_x_axis(fig):
    ax: plt.Axes = fig.axes[0]
    # ax.xaxis.axis_date(tz=HOME_TZ)
    # logging.info(HOME_TZ)
    ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 2)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%I%p'))
    ax.grid(True)
    fig.autofmt_xdate()


HOME_TZ = datetime.now().astimezone().tzinfo


@dataclass
class DaylightAdjuster:
    location: pvlib.location.Location
    brightness_range: Iterable[int] = field(default=(0, 100))
    periods: InitVar[int] = field(default=200)
    datetime: datetime = field(default_factory=datetime.now)

    def __post_init__(self, periods: int):
        self.logger: logging.Logger = logging.getLogger(type(self).__name__)
        today = self.datetime.date()
        times = pd.date_range(
            today, today + timedelta(days=1),
            periods=periods,
            tz=HOME_TZ
        )
        self.logger.info(
            f'{type(times).__name__}:\n' +
            '\n'.join(f'  {dt}' for dt in times[:5]) +
            '\n  ...\n' +
            '\n'.join(f'  {dt}' for dt in times[-5:])
        )

        df = self.location.get_solarposition(times)
        df.index = df.index.tz_localize(None)

        min_e, max_e = df['elevation'].min(), df['elevation'].max()
        self.elevation_range = (min_e, max_e)

        df['pct_elevation'] = (df['elevation'] - min_e) / (max_e - min_e)
        df['brightness'] = (df['pct_elevation'] * (self.brightness_range[1] - self.brightness_range[0])
                            ) + self.brightness_range[0]
        # df['brightness'] = df['brightness'].round(0).astype(int)
        self.df = df[['elevation', 'pct_elevation', 'brightness']]

    @property
    def elevation(self):
        return self.df['elevation']

    def elevation_fig(self):
        fig, ax = plt.subplots(figsize=(10, 7))
        handles = ax.plot(self.elevation)

        ax.set_ylabel('Elevation')
        ax.set_ylim(-100, 100)
        format_x_axis(fig)
        ax.set_xlim(self.df.index[0], self.df.index[-1])

        ax2 = ax.twinx()
        handles.extend(ax2.plot(
            self.df['brightness'], 'r',
            # drawstyle='steps'
        ))
        ax2.set_ylabel('Brightness')
        ax2.set_ylim(0, 255)

        handles.append(ax.axvline(datetime.now(),
                                  linestyle='--',
                                  color='g'))

        handles.append(ax2.axhline(self.get_brightness(),
                                   linestyle='--',
                                   color='r'))

        handles.append(ax.axhline(self.get_elevation(),
                                  linestyle='--',
                                  color=handles[0].get_color()))

        ax.legend(handles=handles, loc='lower center', labels=[
            'Sun Elevation Angle',
            'Brightness Setting',
            'Current Time',
            'Current Brightness',
            'Current Elevation'
        ])

        fig.tight_layout()
        plt.close(fig)
        return fig

    def get_solar_position(self, dt: datetime = None):
        dt = dt or datetime.now()

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=HOME_TZ)

        return pvlib.solarposition.get_solarposition(
            dt.astimezone(None),
            latitude=self.location.latitude,
            longitude=self.location.longitude
        )

    def get_elevation(self, time=None):
        time = time or datetime.now()
        return self.get_solar_position(dt=time).iloc[0].loc['elevation']

    def get_brightness(self, time=None):
        time = time or datetime.now()

        min_e, max_e = self.elevation_range
        rng_e = max_e - min_e

        min_b, max_b = self.brightness_range
        rng_b = max_b - min_b

        current_elevation = self.get_elevation(time=time)
        pct = (current_elevation - min_e) / rng_e
        current_brightness = (pct * rng_b) + min_b

        # self.logger.info(time)
        # self.logger.info(f'Elevation: {current_elevation:.0f}, {pct*100:.1f}%')
        # self.logger.info(f'Brightness: {current_brightness:.0f}')

        print(time)
        print(f'Elevation: {current_elevation:.0f}, {pct*100:.1f}%')
        print(f'Brightness: {current_brightness:.0f}')

        return int(round(current_brightness))
