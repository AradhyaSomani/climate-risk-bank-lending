# DataMeet Census 2011 district boundaries

- **Source:** DataMeet India community, github.com/datameet/maps, `Districts/Census_2011/2011_Dist.shp`.
- **Licence:** CC BY 4.0 for the data (repository README); attribute "DataMeet India community".
- **Coverage:** 641 polygons with `censuscode` (Census 2011 district code, 1 to 640, plus one polygon coded 0), `DISTRICT`, `ST_NM`; WGS 84. 99.8% of geometries valid as downloaded.
- **Role:** provisional geometry for A's zonal statistics until B's `district_master.parquet` (contract C1) is built; the district id is the same Census 2011 code, so switching is a file change only.
- **Known problems:** the polygon coded 0 is "Data Not Available" in Jammu & Kashmir and is dropped; India's official external boundary differs from some international datasets; a few invalid rings need `make_valid`.
