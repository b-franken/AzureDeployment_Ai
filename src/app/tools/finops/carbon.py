from __future__ import annotations


class CarbonDataService:
    def __init__(self) -> None:
        self._region_intensity_g_per_kwh: dict[str, float] = {
            "westeurope": 270.0,
            "northeurope": 120.0,
            "uksouth": 180.0,
            "francecentral": 60.0,
            "swedencentral": 40.0,
            "norwayeast": 30.0,
            "germanywestcentral": 200.0,
        }

    async def get_intensity(self, region: str) -> float | None:
        key = (region or "").replace(" ", "").lower()
        return self._region_intensity_g_per_kwh.get(key)

    async def find_greener_regions(self, region: str, *, min_delta: float = 0.2) -> list[str]:
        base = await self.get_intensity(region)
        if base is None:
            return []
        threshold = base * (1.0 - min_delta)
        return [r for r, v in self._region_intensity_g_per_kwh.items() if v <= threshold]
