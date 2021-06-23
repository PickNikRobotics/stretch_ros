![Stretch ROS Banner](./images/banner.png)

# Galactic Demo

## Setting up ROS 2 on the Robot
0. Update the firmware while using 18.04
 * Start by checking out the new experimental branch of firmware:
    * `cd ~/repos/stretch_firmware`
    * `git pull`
    * `git checkout feature/waypoint_trajectories_py3`
 * Follow the directions [from the `stretch_firmware` repo](https://github.com/hello-robot/stretch_firmware/blob/master/README.md#updating-stretch-firmware) from there.
1. Install a [partition](https://help.ubuntu.com/stable/ubuntu-help/disk-partitions.html.en) on your robot with [Ubuntu 20.04](https://releases.ubuntu.com/20.04/ubuntu-20.04.2.0-desktop-amd64.iso)
2. Copy files from your 18.04 partition to the same places in the 20.04 partition
 * `/etc/udev/rules.d/9*`
 * `~/.config/autostart/hello_robot_*.desktop`
 * `~/stretch_user/`
3. Copy the lines matching `export HELLO_FLEET` from the 18.04 `.bashrc` to the 20.04 .bashrc
3. Install [ROS 2 Galactic](https://docs.ros.org/en/galactic/Installation/Prerelease-Testing.html#debian-testing-repository)
 * When following those instructions instead of `sudo apt install ros-galactic-my-just-released-package` do `sudo apt install ros-galactic-ros-core`
4. Add `$USER` to `dialout input` groups
6. Install Realsense Drivers
 * `sudo apt-key adv --keyserver keys.gnupg.net --recv-key F6E65AC044F831AC80A06380C8B3A55A6F3EFCDE || sudo apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-key F6E65AC044F831AC80A06380C8B3A55A6F3EFCDE`
 * `sudo add-apt-repository "deb https://librealsense.intel.com/Debian/apt-repo focal main" -u`
 * ` sudo apt install librealsense2-utils librealsense2-dkms`

5. Install some Python3 dependencies with `sudo pip3 install serial psutil opencv-python dynamixel-sdk`
6. Install `stretch_body`
 * `mkdir ~/repos`
 * `cd ~/repos`
 * `git clone https://github.com/PickNikRobotics/stretch_body --branch dlu_devel3`
 * `cd stretch_body/body`
 * `./local_install_py3.sh`
 * `cd ../tools`
 * `./local_install.sh`

7. Set up the ROS2 Workspace
 * `mkdir -p ~/galactic_ws/src`
 * `cd ~/galactic_ws/src`
 * `wget https://raw.githubusercontent.com/PickNikRobotics/stretch_ros/galactic_devel/robot.repos`
 * `vcs import < robot.repos`
 * `rosdep update`
 * `rosdep install -r --from-paths . --ignore-src --rosdistro galactic -y`
 * `cd ~/galactic_ws`
 * `colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release --packages-skip stretch_moveit_config galactic_demo`
 * `cp $HELLO_FLEET_PATH/$HELLO_FLEET_ID/exported_urdf/stretch.urdf ~/galactic_ws/src/stretch_ros/stretch_description/urdf`
 * `cp $HELLO_FLEET_PATH/$HELLO_FLEET_ID/exported_urdf/controller_calibration_head.yaml ~/galactic_ws/src/stretch_ros/stretch_core/config`
 * `echo "source ~/galactic_ws/install/setup.bash" >> ~/.bashrc`
7. Install the script to stop the laser from always spinning
 * `wget https://raw.githubusercontent.com/hello-robot/stretch_install/master/factory/hello_robot_lrf_off.py`
 * `chmod +x hello_robot_lrf_off.py`
 * `sudo cp hello_robot_lrf_off.py /usr/bin/`


## Running on the robot
    ros2 launch stretch_core stretch_robot.launch.py


## Setting up your computer
0. These instructions assume you have Ubuntu 20.04 installed with ROS 2 Galactic
 * One additional dependency that I'm not sure where it belongs yet is `ros-galactic-qt-gui-cpp`
1. Set up the ROS2 Workspace
 * `mkdir -p ~/hello2_ws/src`
 * `cd ~/hello2_ws/src`
 * `wget https://raw.githubusercontent.com/PickNikRobotics/stretch_ros/galactic_devel/stretch_ros.repos`
 * `vcs import < stretch_ros.repos`
 * `rosdep install -r --from-paths . --ignore-src --rosdistro galactic -y`
 * `cd ~/hello2_ws`
 * [`colcon build --event-handlers desktop_notification- status- --packages-skip realsense_camera2 --cmake-args -DCMAKE_BUILD_TYPE=Release`](https://moveit.ros.org/install-moveit2/source/)

## Running on your computer
    source ~/hello2_ws/install/setup.bash
    ros2 run stretch_dashboard dashboard --force-discover &
    ros2 launch stretch_moveit_config demo.launch.py

## Notes:
### Variables that may change as things get merged in
 * feature/waypoint_trajectories_py3
 * dlu_devel3
 * galactic_devel
