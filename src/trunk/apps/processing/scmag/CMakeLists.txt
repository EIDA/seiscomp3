SET(MAG_TARGET scmag)

SET(
	MAG_SOURCES
		dmutil.cpp
		magtool.cpp
		scmagtool.cpp
)

INCLUDE_DIRECTORIES(${Boost_INCLUDE_DIRS})
INCLUDE_DIRECTORIES(.)

SC_ADD_EXECUTABLE(MAG ${MAG_TARGET})
SC_LINK_LIBRARIES_INTERNAL(${MAG_TARGET} client)
SC_INSTALL_INIT(${MAG_TARGET} ../../templates/initd.py)

FILE(GLOB descs "${CMAKE_CURRENT_SOURCE_DIR}/descriptions/*.xml")
INSTALL(FILES ${descs} DESTINATION ${SC3_PACKAGE_APP_DESC_DIR})
