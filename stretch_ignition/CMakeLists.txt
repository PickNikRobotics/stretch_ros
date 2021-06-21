cmake_minimum_required(VERSION 3.10.2)
project(stretch_ignition)

find_package(ament_cmake REQUIRED)

install(DIRECTORY worlds rviz launch DESTINATION share/${PROJECT_NAME})

ament_package()
