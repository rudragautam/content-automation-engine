"""US market configuration."""

from dataclasses import dataclass


@dataclass(frozen=True)
class USMarketConfig:
    rss_feed_urls: tuple[str, ...] = (
        "https://feeds.npr.org/1001/feed.json",
        "https://feeds.reuters.com/reuters/topNews",
    )
    gdelt_query_url: str = "https://api.gdeltproject.org/api/v2/doc/doc"
    gdelt_params: dict[str, str] = None
    google_trends_rss_url: str = "https://trends.google.com/trending/rss?geo=US"
    region: str = "US"


if USMarketConfig.gdelt_params is None:
    US_MARKET = USMarketConfig(
        rss_feed_urls=(
            "https://feeds.npr.org/1001/feed.json",
            "https://feeds.reuters.com/reuters/topNews",
        ),
        gdelt_query_url="https://api.gdeltproject.org/api/v2/doc/doc",
        gdelt_params={
            "query": "United States",
            "timespan": "24H",
            "mode": "ArtList",
            "format": "json",
        },
        google_trends_rss_url="https://trends.google.com/trending/rss?geo=US",
        region="US",
    )
else:
    US_MARKET = USMarketConfig()
