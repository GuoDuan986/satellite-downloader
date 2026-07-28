class SatelliteDownloaderError(Exception):
    """Base exception shown to the user."""


class AuthenticationError(SatelliteDownloaderError):
    pass


class CatalogueError(SatelliteDownloaderError):
    pass


class DownloadError(SatelliteDownloaderError):
    pass


class DownloadCancelled(SatelliteDownloaderError):
    pass

