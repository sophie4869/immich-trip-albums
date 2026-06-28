from trip_albums.geo import haversine_km, centroid


def test_haversine_known_distance():
    # Paris -> London is roughly 343 km.
    d = haversine_km(48.8566, 2.3522, 51.5074, -0.1278)
    assert 330 < d < 355


def test_haversine_zero():
    assert haversine_km(1.0, 2.0, 1.0, 2.0) == 0.0


def test_centroid_mean_of_points():
    assert centroid([(0.0, 0.0), (2.0, 4.0)]) == (1.0, 2.0)


def test_centroid_none_when_empty():
    assert centroid([]) is None
