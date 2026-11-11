# DataMeet Census 2011 district boundaries

- **Source:** DataMeet India community, github.com/datameet/maps, `Districts/Census_2011/2011_Dist.shp`.
- **Licence:** CC BY 4.0 for the data (repository README); attribute "DataMeet India community".
- **Coverage:** 641 polygons with `censuscode` (Census 2011 district code, 1 to 640, plus one polygon coded 0), `DISTRICT`, `ST_NM`; WGS 84. 99.8% of geometries valid as downloaded.
- **Role:** the geometry, names and state names of `district_master.parquet` (contract C1, `cri.geo.district_master`), which A's zonal statistics read once it exists. The master keeps this file's names and ids, so A's tables do not change when they switch to it.
- **Known problems:** the polygon coded 0 is "Data Not Available" in Jammu & Kashmir and is dropped; India's official external boundary differs from some international datasets; a few invalid rings need `make_valid`.
