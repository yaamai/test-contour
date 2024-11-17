from pyproj import Transformer
import shapely
import shapely.ops
from shapely.geometry import shape
from pyproj import CRS
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info
from typing import Annotated
import pg8000.native
import geojson
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

def query_dem_colormap_png(area: geojson.Polygon) -> bytes | None:
    con = pg8000.native.Connection(host="192.168.130.104", port=15432, user="renderer", database="gis", password="renderer")
    ret = con.run("""
        SELECT
            ST_AsPNG(
                ST_ColorMap(
                    ST_Reclass(
                        ST_Union(rast),
                        1,
                        '0-32767:0-65535',
                        '16BUI',
                        0
                    ),
                    1,
                    'pseudocolor'
                )
            )
        FROM nasdem
        WHERE rast && ST_GeomFromGeoJSON(:geojson);
    """, geojson=geojson.dumps(area))
    con.close()

    if ret is None:
        return ret
    return ret[0][0]


def query_dem_contour_geojson(area: geojson.Polygon) -> geojson.FeatureCollection | None:
    con = pg8000.native.Connection(host="192.168.130.104", port=15432, user="renderer", database="gis", password="renderer")
#    ret = con.run("""
#        SELECT
#            json_build_object(
#                'type', 'FeatureCollection',
#                'features', json_agg(features)
#            )
#        FROM
#            LATERAL (
#                SELECT
#                    ST_AsGeoJSON(
#                        ST_Contour(
#                            ST_Reclass(
#                                ST_Union(rast),
#                                1,
#                                '0-32767:0-65535',
#                                '16BUI',
#                                0
#                            ),
#                            1,
#                            100
#                        )
#                    )
#                FROM nasdem
#                WHERE rast && ST_GeomFromGeoJSON(:geojson)
#            ) features;
#    """, geojson=geojson.dumps(area))
    ret = con.run("""
        WITH contour_features AS (
                SELECT
                    ST_AsGeoJSON(
                        ST_Contour(
                            ST_Reclass(
                                ST_Union(rast),
                                1,
                                '0-32767:0-65535',
                                '16BUI',
                                0
                            ),
                            1,
                            50
                        )
                    )::json AS geojson
                FROM nasdem
                WHERE rast && ST_GeomFromGeoJSON(:geojson)
                )
        SELECT
            json_build_object(
                'type', 'FeatureCollection',
                'features', json_agg(geojson)
            )
        FROM contour_features;
    """, geojson=geojson.dumps(area))
    con.close()
    # print(len(ret))
    # print(len(ret[0]))
    # print(ret[0])

    if ret is None:
        return ret

    return geojson.GeoJSON.to_instance(ret[0][0])


def query_transform_func(area_dict: dict):

    area = shape(area_dict)
    minx, miny, maxx, maxy = area.bounds
    # print(minx, miny, maxx, maxy)
    utm_crs_list = query_utm_crs_info(
        datum_name="WGS 84",
        area_of_interest=AreaOfInterest(
            west_lon_degree=minx,
            south_lat_degree=miny,
            east_lon_degree=maxx,
            north_lat_degree=maxy,
        ),
    )
    if not utm_crs_list:
        return None

    geojson_crs = CRS.from_epsg(4326)
    utm_crs = CRS.from_epsg(utm_crs_list[0].code)
    return Transformer.from_crs(geojson_crs, utm_crs, always_xy=True).transform


def calc_bounding_box(polygon: dict):
    area = shape(polygon)
    minx, miny, maxx, maxy = area.bounds
    return shapely.Polygon([(minx, miny), (minx, maxy), (maxx, maxy), (maxx, miny)])

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://192.168.130.104:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/contours")
async def get_contours(area: dict) -> JSONResponse:
    # print(area)
    tf = query_transform_func(area)
    if not tf:
        print(f"can't determine utm zone")
        return

    bndbox = shapely.ops.transform(tf, calc_bounding_box(area))
    area_kilo = (bndbox.area / (1000*1000))
    print(f"bndbox={geojson.dumps(bndbox)}, area={area_kilo} {bndbox.area}")
    if area_kilo > 150:
        print(f"too large area: {area_kilo}")
        return

    area = geojson.GeoJSON.to_instance(area)
    # print(area)
    # print(area.is_valid)

    contours = query_dem_contour_geojson(area)
    return JSONResponse(content=contours)


# area = geojson.loads('{ "type": "Polygon", "coordinates": [ [ [ 140.66961236902182, 36.94557532907991 ], [ 140.6945890993685, 36.94557532907991 ], [ 140.6945890993685, 36.93609127679686 ], [ 140.66961236902182, 36.93609127679686 ], [ 140.66961236902182, 36.94557532907991 ] ] ] }')
# contours = query_dem_contour_geojson(area)



# area = geojson.loads('{"type":"Polygon","coordinates":[[[139.062195,35.397866],[138.693981,35.397866],[138.693981,35.206636],[139.062195,35.206636],[139.062195,35.397866]]]}')
"""
# query_dem_colormap_png(area)
breakpoint()
>>>
>>> # Create a temporary table
>>>
>>> con.run("CREATE TEMPORARY TABLE book (id SERIAL, title TEXT)")
>>>
>>> # Populate the table
>>>
>>> for title in ("Ender's Game", "The Magus"):
...     con.run("INSERT INTO book (title) VALUES (:title)", title=title)
>>>
>>> # Print all the rows in the table
>>>
>>> for row in con.run("SELECT * FROM book"):
...     print(row)
[1, "Ender's Game"]
[2, 'The Magus']
>>>
>>> con.close()
"""
