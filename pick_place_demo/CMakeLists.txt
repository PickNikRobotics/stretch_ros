cmake_minimum_required(VERSION 3.5)
project(pick_place_demo)

# Default to C++17
if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(pick_place_task REQUIRED)
find_package(moveit_task_constructor_core REQUIRED)
find_package(moveit_core REQUIRED)
find_package(rclcpp REQUIRED)
find_package(moveit_ros_planning_interface REQUIRED)
find_package(geometry_msgs REQUIRED)

add_executable(${PROJECT_NAME}
  src/pick_place_demo.cpp
)
ament_target_dependencies(${PROJECT_NAME}
  pick_place_task
  moveit_task_constructor_core
  rclcpp
  moveit_core
  moveit_ros_planning_interface
  geometry_msgs
)

install(DIRECTORY launch rviz config
  DESTINATION share/${PROJECT_NAME}
)
install(TARGETS ${PROJECT_NAME}
  # ARCHIVE DESTINATION lib
  # LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/${PROJECT_NAME}
)

ament_package()
