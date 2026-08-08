import yfinance as yf
from resistance_breakout_indicator import ResistanceBreakoutIndicator
import mplfinance as mpf
import numpy as np
import yahooquery as yq
import pandas as pd


class SMA150Indicator:
    def __init__(self, sma_period=150, proximity_pct=0.03, history_period='1y'):
        self.sma_period = sma_period
        self.proximity_pct = proximity_pct
        self.history_period = history_period
        self.resistance_indicator = ResistanceBreakoutIndicator()
        self.ticker_bars = None
        self.resistance_lines = []

    def download_data(self, ticker):
        try:
            data = yf.download(ticker, period=self.history_period, interval='1d', progress=False, auto_adjust=True)
            return data if not data.empty else None
        except Exception as e:
            return None

    def calculate_sma(self, data):
        data[f'SMA_{self.sma_period}'] = data['Close'].rolling(window=self.sma_period).mean()
        return data

    def check_sustained_150sma_indicator(self, data, ticker, start_day):
        for day in range(1, start_day):
            current_sma = data[f'SMA_{self.sma_period}'].iloc[-day]
            current_close_price = (data['Close'].iloc[-day])[ticker.upper()]
            if current_close_price < current_sma:
                return False
        return True

    def check_around_resistance(self, ticker_name):
        data = yq.Ticker(ticker_name).history(period=self.history_period, interval='1d').reset_index(level=0, drop=True)
        return self.resistance_indicator.find_swing_general_picks(data)

    def find_last_150sma_crossing(self, data, ticker, max_days=20, min_days=2):
        for day in range(min_days, max_days + 1):
            current_sma = data[f'SMA_{self.sma_period}'].iloc[-day]
            current_close_price = (data['Close'].iloc[-day])[ticker.upper()]
            previous_close_price = (data['Close'].iloc[-(day + 1)])[ticker.upper()]

            if current_close_price > current_sma > previous_close_price:
                return {
                    'Ticker': ticker,
                    'Signal': f'passed {day} days ago from {previous_close_price} to {current_close_price}',
                    'Current Price': current_close_price,
                    f'SMA_{self.sma_period}': current_sma,
                    'Day': day
                }

        return None

    def analyze_ticker(self, ticker):
        print(f'analyzing {ticker}')
        data = self.download_data(ticker)
        if data is None or data.empty:
            return None

        # Check if we have enough data
        if len(data) < self.sma_period:
            print(f"Skipping {ticker}: Not enough data for {self.sma_period} days.")
            return None

        # Calculate SMA
        data = self.calculate_sma(data)
        is_crossed_150 = self.find_last_150sma_crossing(data, ticker)
        if is_crossed_150 is not None:
            is_sustained = self.check_sustained_150sma_indicator(data, ticker, is_crossed_150.get('Day'))
            if is_sustained:
                return is_crossed_150
        return None

    @staticmethod
    def draw_stock_view(ticker_bars, resistances, ticker_name):
        add_plot = [mpf.make_addplot(np.full(ticker_bars.shape[0], resistance), color='r', linestyle='--') for
                    resistance in
                    resistances]

        ticker_bars.index = pd.to_datetime(ticker_bars.index, utc=True)

        mpf.plot(
            ticker_bars,
            type='candle',
            style='charles',
            title=ticker_name,
            volume=True,
            addplot=add_plot
        )

    def scan_tickers(self, tickers):
        bullish_stocks = []
        print(f"Starting scan for SMA {self.sma_period} crossover...")

        for ticker in tickers:
            try:
                result = self.analyze_ticker(ticker)
                if result:
                    bullish_stocks.append(result)
            except Exception as e:

                pass

        return pd.DataFrame(bullish_stocks)
