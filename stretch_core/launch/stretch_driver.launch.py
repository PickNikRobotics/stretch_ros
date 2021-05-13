import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration

from launch_ros.actions import Node

import xacro


def generate_launch_description():
    robot_description_path = os.path.join(get_package_share_directory('stretch_description'),
                                          'urdf',
                                          'stretch.urdf')

    calibrated_controller_yaml_file = os.path.join(get_package_share_directory('stretch_core'),
                                                   'config',
                                                   'controller_calibration_head.yaml')

    joint_state_publisher = Node(package='joint_state_publisher',
                                 executable='joint_state_publisher',
                                 name='joint_state_publisher',
                                 arguments=[robot_description_path],
                                 output='log',
                                 parameters=[{'source_list': ['/stretch/joint_states']},
                                             {'rate': 15}])

    robot_state_publisher = Node(package='robot_state_publisher',
                                 executable='robot_state_publisher',
                                 name='robot_state_publisher',
                                 output='both',
                                 parameters=[{'robot_description': xacro.process_file(robot_description_path).toxml()},
                                             {'publish_frequency': 15.0}])

    aggregator = Node(package='diagnostic_aggregator',
                      executable='aggregator_node',
                      output='log',
                      parameters=[os.path.join(get_package_share_directory('stretch_core'), 'config/diagnostics.yaml')])

    declare_broadcast_odom_tf_arg = DeclareLaunchArgument(
        'broadcast_odom_tf',
        default_value=str(False),
        description='Whether to broadcast the odom TF'
    )

    declare_fail_out_of_range_goal_arg = DeclareLaunchArgument(
        'fail_out_of_range_goal',
        default_value=str(True),
        description='Whether the motion action servers fail on out-of-range commands'
    )

    declare_mode_arg = DeclareLaunchArgument(
        'mode',
        default_value=str('position'),
        description='The mode in which the ROS driver commands the robot'
    )

    stretch_driver = Node(package='stretch_core',
                          executable='stretch_driver',
                          name='stretch_driver',
                          emulate_tty=True,
                          remappings=[('cmd_vel', '/stretch/cmd_vel'),
                                      ('joint_states', '/stretch/joint_states')],
                          parameters=[{'rate': 25.0},
                                      {'timeout': 0.5},
                                      {'controller_calibration_file': calibrated_controller_yaml_file},
                                      {'broadcast_odom_tf': LaunchConfiguration('broadcast_odom_tf')},
                                      {'fail_out_of_range_goal': LaunchConfiguration('fail_out_of_range_goal')},
                                      {'mode': LaunchConfiguration('mode')}])

    return LaunchDescription([declare_broadcast_odom_tf_arg,
                              declare_fail_out_of_range_goal_arg,
                              declare_mode_arg,
                              joint_state_publisher,
                              robot_state_publisher,
                              aggregator,
                              stretch_driver])
