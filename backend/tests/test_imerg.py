"""NASA IMERG: grid cell maths and reading the OPeNDAP ASCII reply."""
from app.services.imerg import cell, parse


def test_cell_of_aizawl():
    i_lon, i_lat, glat, glon = cell(23.684, 92.715)
    assert (i_lon, i_lat) == (2727, 1136) and (glat, glon) == (23.65, 92.75)


def test_parse_single_cell_reply():
    body = ("Dataset: 3B-DAY.MS.MRG.3IMERG.20240527-S000000-E235959.V07B.nc4\n"
            "precipitation.lat, 23.65\n"
            "precipitation.precipitation[precipitation.time=16583][precipitation.lon=92.75], 172.8\n")
    assert parse(body) == 172.8
