from pytickersymbols import PyTickerSymbols

class TickerFinder:
    def __init__(self):
        self.ticker_list = []

    def find_tickers(self):
        stocks = PyTickerSymbols()
        total_stocks = []
        total_stocks.extend(stocks.get_stocks_by_index('DOW JONES'))
        total_stocks.extend(stocks.get_stocks_by_index('NASDAQ 100'))
        total_stocks.extend(stocks.get_stocks_by_index("S&P 500"))
        sp500_ticker_names = (t.get('symbol') for t in list(total_stocks))
        print(sp500_ticker_names)
        return sp500_ticker_names
