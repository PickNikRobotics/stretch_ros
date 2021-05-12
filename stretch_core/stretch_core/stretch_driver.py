#! /usr/bin/env python
from __future__ import print_function

import threading

import yaml
import numpy as np
import threading
from .rwlock import RWLock
import stretch_body.robot as rb
from stretch_body.hello_utils import ThreadServiceExit

import tf2_ros
import pyquaternion

import rclpy
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from geometry_msgs.msg import Quaternion
from geometry_msgs.msg import Twist
from geometry_msgs.msg import TransformStamped

from std_srvs.srv import Trigger
from std_srvs.srv import SetBool

from nav_msgs.msg import Odometry
from sensor_msgs.msg import BatteryState, JointState, Imu, MagneticField
from std_msgs.msg import Header, Bool, String

from hello_helpers.gripper_conversion import GripperConversion
from .joint_trajectory_server import JointTrajectoryAction
from .stretch_diagnostics import StretchDiagnostics

GRIPPER_DEBUG = False
BACKLASH_DEBUG = False


class StretchBodyNode(Node):

    def __init__(self):
        super().__init__('stretch_driver')
        self.use_robotis_head = True
        self.use_robotis_end_of_arm = True

        self.default_goal_timeout_s = 10.0
        self.default_goal_timeout_duration = Duration(seconds=self.default_goal_timeout_s)

        # Initialize calibration offsets
        self.head_tilt_calibrated_offset_rad = 0.0
        self.head_pan_calibrated_offset_rad = 0.0

        # Initialize backlash state
        self.backlash_state = {'head_tilt_looking_up' : False,
                               'head_pan_looked_left' : False,
                               'wrist_extension_retracted' : False}

        # Initialize backlash offsets
        self.head_pan_calibrated_looked_left_offset_rad = 0.0
        self.head_tilt_calibrated_looking_up_offset_rad = 0.0
        self.wrist_extension_calibrated_retracted_offset_m = 0.0
        self.head_tilt_backlash_transition_angle_rad = -0.4

        self.gripper_conversion = GripperConversion()

        self.mobile_base_manipulation_origin = None #{'x':None, 'y':None, 'theta':None}

        self.robot_stop_lock = threading.Lock()
        self.stop_the_robot = False

        self.robot_mode_rwlock = RWLock()
        self.robot_mode = None

        self.ros_setup()

    ###### MOBILE BASE VELOCITY METHODS #######

    def set_mobile_base_velocity_callback(self, twist):
        self.robot_mode_rwlock.acquire_read()
        if self.robot_mode != 'navigation':
            error_string = '{0} action server must be in navigation mode to receive a twist on cmd_vel. Current mode = {1}.'.format(self.node_name, self.robot_mode)
            self.get_logger().error(error_string)
            return
        self.linear_velocity_mps = twist.linear.x
        self.angular_velocity_radps = twist.angular.z
        self.last_twist_time = self.get_clock().now()
        self.robot_mode_rwlock.release_read()

    def command_mobile_base_velocity_and_publish_state(self):
        self.robot_mode_rwlock.acquire_read()

        if BACKLASH_DEBUG:
            print('***')
            print('self.backlash_state =', self.backlash_state)

        # set new mobile base velocities, if appropriate
        # check on thread safety for this with callback that sets velocity command values
        if self.robot_mode == 'navigation':
            time_since_last_twist = self.get_clock().now() - self.last_twist_time
            if time_since_last_twist < self.timeout:
                self.robot.base.set_velocity(self.linear_velocity_mps, self.angular_velocity_radps)
                self.robot.push_command()
            else:
                # Too much information in general, although it could be blocked, since it's just INFO.
                self.robot.base.set_velocity(0.0, 0.0)
                self.robot.push_command()

        # get copy of the current robot status (uses lock held by the robot)
        robot_status = self.robot.get_status()


        # In the future, consider using time stamps from the robot's
        # motor control boards and other boards. These would need to
        # be synchronized with the ros clock.
        #robot_time = robot_status['timestamp_pc']
        #self.get_logger().info('robot_time =', robot_time)
        #current_time = rospy.Time.from_sec(robot_time)

        current_time = self.get_clock().now()
        current_stamp = current_time.to_msg()

        # obtain odometry
        # assign relevant base status to variables
        base_status = robot_status['base']
        x = base_status['x']
        x_raw = x
        y = base_status['y']
        theta = base_status['theta']
        x_vel = float(base_status['x_vel'])
        x_vel_raw = x_vel
        y_vel = base_status['y_vel']
        x_effort = base_status['effort'][0]
        x_effort_raw = x_effort
        theta_vel = float(base_status['theta_vel'])
        pose_time_s = base_status['pose_time_s']

        if self.robot_mode == 'manipulation':
            x = self.mobile_base_manipulation_origin['x']
            x_vel = 0.0
            x_effort = 0.0

        # Convert to floats for ROS2 message definition compatibility
        x = float(x)
        y = float(y)

        # assign relevant arm status to variables
        arm_status = robot_status['arm']
        if self.backlash_state['wrist_extension_retracted']:
            arm_backlash_correction = self.wrist_extension_calibrated_retracted_offset_m
        else:
            arm_backlash_correction = 0.0

        if BACKLASH_DEBUG:
            print('arm_backlash_correction =', arm_backlash_correction)
        pos_out = arm_status['pos'] + arm_backlash_correction
        vel_out = arm_status['vel']
        eff_out = arm_status['motor']['effort']

        lift_status = robot_status['lift']
        pos_up = lift_status['pos']
        vel_up = lift_status['vel']
        eff_up = lift_status['motor']['effort']

        if self.use_robotis_end_of_arm:
            # assign relevant wrist status to variables
            wrist_status = robot_status['end_of_arm']['wrist_yaw']
            wrist_rad = wrist_status['pos']
            wrist_vel = wrist_status['vel']
            wrist_effort = wrist_status['effort']

            # assign relevant gripper status to variables
            gripper_status = robot_status['end_of_arm']['stretch_gripper']
            if GRIPPER_DEBUG:
                print('-----------------------')
                print('gripper_status[\'pos\'] =', gripper_status['pos'])
                print('gripper_status[\'pos_pct\'] =', gripper_status['pos_pct'])
            gripper_aperture_m, gripper_finger_rad, gripper_finger_effort, gripper_finger_vel = self.gripper_conversion.status_to_all(gripper_status)
            if GRIPPER_DEBUG:
                print('gripper_aperture_m =', gripper_aperture_m)
                print('gripper_finger_rad =', gripper_finger_rad)
                print('-----------------------')

        if self.use_robotis_head:
            # assign relevant head pan status to variables
            head_pan_status = robot_status['head']['head_pan']
            if self.backlash_state['head_pan_looked_left']:
                pan_backlash_correction = self.head_pan_calibrated_looked_left_offset_rad
            else:
                pan_backlash_correction = 0.0
            if BACKLASH_DEBUG:
                print('pan_backlash_correction =', pan_backlash_correction)
            head_pan_rad = head_pan_status['pos'] + self.head_pan_calibrated_offset_rad + pan_backlash_correction
            head_pan_vel = head_pan_status['vel']
            head_pan_effort = head_pan_status['effort']

            # assign relevant head tilt status to variables
            head_tilt_status = robot_status['head']['head_tilt']
            if self.backlash_state['head_tilt_looking_up']:
                tilt_backlash_correction = self.head_tilt_calibrated_looking_up_offset_rad
            else:
                tilt_backlash_correction = 0.0
            if BACKLASH_DEBUG:
                print('tilt_backlash_correction =', tilt_backlash_correction)
            head_tilt_rad = head_tilt_status['pos'] + self.head_tilt_calibrated_offset_rad + tilt_backlash_correction
            head_tilt_vel = head_tilt_status['vel']
            head_tilt_effort = head_tilt_status['effort']

        q = pyquaternion.Quaternion(axis=[0, 0, 1], angle=theta)

        if self.broadcast_odom_tf:
            # publish odometry via TF
            t = TransformStamped()
            t.header.stamp = current_stamp
            t.header.frame_id = self.odom_frame_id
            t.child_frame_id = self.base_frame_id
            t.transform.translation.x = x
            t.transform.translation.y = y
            t.transform.translation.z = 0.0
            t.transform.rotation.x = q.x
            t.transform.rotation.y = q.y
            t.transform.rotation.z = q.z
            t.transform.rotation.w = q.w
            self.tf_broadcaster.sendTransform(t)

        # publish odometry via the odom topic
        odom = Odometry()
        odom.header.stamp = current_stamp
        odom.header.frame_id = self.odom_frame_id
        odom.child_frame_id = self.base_frame_id
        odom.pose.pose.position.x = x
        odom.pose.pose.position.y = y
        odom.pose.pose.orientation.x = q.x
        odom.pose.pose.orientation.y = q.y
        odom.pose.pose.orientation.z = q.z
        odom.pose.pose.orientation.w = q.w
        odom.twist.twist.linear.x = x_vel
        odom.twist.twist.angular.z = theta_vel
        self.odom_pub.publish(odom)

        # TODO: Add way to determine if the robot is charging
        # TODO: Calculate the percentage
        battery_state = BatteryState()
        invalid_reading = float('NaN')
        battery_state.header.stamp = current_stamp
        battery_state.voltage = float(robot_status['pimu']['voltage'])
        battery_state.current = float(robot_status['pimu']['current'])
        battery_state.charge = invalid_reading
        battery_state.capacity = invalid_reading
        battery_state.percentage = invalid_reading
        battery_state.design_capacity = 18.0
        battery_state.present = True
        self.power_pub.publish(battery_state)

        calibration_status = Bool()
        calibration_status.data = self.robot.is_calibrated()
        self.calibration_pub.publish(calibration_status)

        mode_msg = String()
        mode_msg.data = self.robot_mode
        self.mode_pub.publish(mode_msg)

        # publish joint state for the arm
        joint_state = JointState()
        joint_state.header.stamp = current_stamp
        # joint_arm_l3 is the most proximal and joint_arm_l0 is the
        # most distal joint of the telescoping arm model. The joints
        # are connected in series such that moving the most proximal
        # joint moves all the other joints in the global frame.
        joint_state.name = ['wrist_extension', 'joint_lift', 'joint_arm_l3', 'joint_arm_l2', 'joint_arm_l1', 'joint_arm_l0']

        # set positions of the telescoping joints
        positions = [pos_out/4.0 for i in range(4)]
        # set lift position
        positions.insert(0, pos_up)
        # set wrist_extension position
        positions.insert(0, pos_out)

        # set velocities of the telescoping joints
        velocities = [vel_out/4.0 for i in range(4)]
        # set lift velocity
        velocities.insert(0, vel_up)
        # set wrist_extension velocity
        velocities.insert(0, vel_out)

        # set efforts of the telescoping joints
        efforts = [eff_out for i in range(4)]
        # set lift effort
        efforts.insert(0, eff_up)
        # set wrist_extension effort
        efforts.insert(0, eff_out)

        if self.use_robotis_head:
            head_joint_names = ['joint_head_pan', 'joint_head_tilt']
            joint_state.name.extend(head_joint_names)

            positions.append(head_pan_rad)
            velocities.append(head_pan_vel)
            efforts.append(head_pan_effort)

            positions.append(head_tilt_rad)
            velocities.append(head_tilt_vel)
            efforts.append(head_tilt_effort)

        if self.use_robotis_end_of_arm:
            end_of_arm_joint_names = ['joint_wrist_yaw', 'joint_gripper_finger_left', 'joint_gripper_finger_right']
            joint_state.name.extend(end_of_arm_joint_names)

            positions.append(wrist_rad)
            velocities.append(wrist_vel)
            efforts.append(wrist_effort)

            positions.append(gripper_finger_rad)
            velocities.append(gripper_finger_vel)
            efforts.append(gripper_finger_effort)

            positions.append(gripper_finger_rad)
            velocities.append(gripper_finger_vel)
            efforts.append(gripper_finger_effort)

        # set virtual joint for mobile base translation
        joint_state.name.append('joint_mobile_base_translation')
        if self.robot_mode == 'manipulation':
            manipulation_translation = x_raw - self.mobile_base_manipulation_origin['x']
            positions.append(manipulation_translation)
            velocities.append(x_vel_raw)
            efforts.append(x_effort_raw)
        else:
            positions.append(0.0)
            velocities.append(0.0)
            efforts.append(0.0)

        # set joint_state
        joint_state.position = list(map(float, positions))
        joint_state.velocity = list(map(float, velocities))
        joint_state.effort = list(map(float, efforts))
        self.joint_state_pub.publish(joint_state)

        ##################################################
        # publish IMU sensor data
        imu_status = robot_status['pimu']['imu']
        ax = imu_status['ax']
        ay = imu_status['ay']
        az = imu_status['az']
        gx = imu_status['gx']
        gy = imu_status['gy']
        gz = imu_status['gz']
        mx = imu_status['mx']
        my = imu_status['my']
        mz = imu_status['mz']

        i = Imu()
        i.header.stamp = current_stamp
        i.header.frame_id = 'imu_mobile_base'
        i.angular_velocity.x = float(gx)
        i.angular_velocity.y = float(gy)
        i.angular_velocity.z = float(gz)

        i.linear_acceleration.x = float(ax)
        i.linear_acceleration.y = float(ay)
        i.linear_acceleration.z = float(az)
        self.imu_mobile_base_pub.publish(i)

        m = MagneticField()
        m.header.stamp = current_stamp
        m.header.frame_id = 'imu_mobile_base'
        self.magnetometer_mobile_base_pub.publish(m)

        accel_status = robot_status['wacc']
        ax = accel_status['ax']
        ay = accel_status['ay']
        az = accel_status['az']

        i = Imu()
        i.header.stamp = current_stamp
        i.header.frame_id = 'accel_wrist'
        i.linear_acceleration.x = float(ax)
        i.linear_acceleration.y = float(ay)
        i.linear_acceleration.z = float(az)
        self.imu_wrist_pub.publish(i)
        ##################################################

        self.robot_mode_rwlock.release_read()

    ######## CHANGE MODES #########

    def change_mode(self, new_mode, code_to_run):
        self.robot_mode_rwlock.acquire_write()
        self.robot_mode = new_mode
        code_to_run()
        self.get_logger().info('{0}: Changed to mode = {1}'.format(self.node_name, self.robot_mode))
        self.robot_mode_rwlock.release_write()

    # TODO : add a freewheel mode or something comparable for the mobile base?

    def turn_on_navigation_mode(self):
        # Navigation mode enables mobile base velocity control via
        # cmd_vel, and disables position-based control of the mobile
        # base.
        def code_to_run():
            self.linear_velocity_mps = 0.0
            self.angular_velocity_radps = 0.0
        self.change_mode('navigation', code_to_run)

    def turn_on_manipulation_mode(self):
        # Manipulation mode enables mobile base translation using
        # position control via joint_mobile_base_translation, and
        # disables velocity control of the mobile base. It also
        # updates the virtual prismatic joint named
        # joint_mobile_base_translation that relates 'floor_link' and
        # 'base_link'. This mode was originally created so that
        # MoveIt! could treat the robot like an arm. This mode does
        # not allow base rotation.
        def code_to_run():
            self.robot.base.enable_pos_incr_mode()
            # get copy of the current robot status (uses lock held by the robot)
            robot_status = self.robot.get_status()
            # obtain odometry
            # assign relevant base status to variables
            base_status = robot_status['base']
            x = base_status['x']
            y = base_status['y']
            theta = base_status['theta']
            self.mobile_base_manipulation_origin = {'x':x, 'y':y, 'theta':theta}
        self.change_mode('manipulation', code_to_run)

    def turn_on_position_mode(self):
        # Position mode enables mobile base translation and rotation
        # using position control with sequential incremental rotations
        # and translations. It also disables velocity control of the
        # mobile base. It does not update the virtual prismatic
        # joint. The frames associated with 'floor_link' and
        # 'base_link' become identical in this mode.
        def code_to_run():
            self.robot.base.enable_pos_incr_mode()
        self.change_mode('position', code_to_run)

    def calibrate(self):
        def code_to_run():
            self.robot.home()
        self.change_mode('calibration', code_to_run)

    ######## SERVICE CALLBACKS #######

    def stop_the_robot_callback(self, request, response):
        with self.robot_stop_lock:
            self.stop_the_robot = True

            self.robot.base.translate_by(0.0)
            self.robot.base.rotate_by(0.0)
            self.robot.arm.move_by(0.0)
            self.robot.lift.move_by(0.0)
            self.robot.push_command()

            self.robot.head.move_by('head_pan', 0.0)
            self.robot.head.move_by('head_tilt', 0.0)
            self.robot.end_of_arm.move_by('wrist_yaw', 0.0)
            self.robot.end_of_arm.move_by('stretch_gripper', 0.0)
            self.robot.push_command()

        self.get_logger().info('Received stop_the_robot service call, so commanded all actuators to stop.')
        response.success = True
        response.message = 'Stopped the robot.'
        return response

    def calibrate_callback(self, request, response):
        self.get_logger().info('Received calibrate_the_robot service call.')

        self.calibrate()

        response.success = True
        response.message = 'Calibrated.'
        return response

    def navigation_mode_service_callback(self, request, response):
        self.turn_on_navigation_mode()
        response.success = True
        response.message = 'Now in navigation mode.'
        return response

    def manipulation_mode_service_callback(self, request, response):
        self.turn_on_manipulation_mode()
        response.success = True
        response.message = 'Now in manipulation mode.'
        return response

    def position_mode_service_callback(self, request, response):
        self.turn_on_position_mode()
        response.success = True
        response.message = 'Now in position mode.'
        return response

    def runstop_service_callback(self, request, response):
        if request.data:
            with self.robot_stop_lock:
                self.stop_the_robot = True

                self.robot.base.translate_by(0.0)
                self.robot.base.rotate_by(0.0)
                self.robot.arm.move_by(0.0)
                self.robot.lift.move_by(0.0)
                self.robot.push_command()

                self.robot.head.move_by('head_pan', 0.0)
                self.robot.head.move_by('head_tilt', 0.0)
                self.robot.end_of_arm.move_by('wrist_yaw', 0.0)
                self.robot.end_of_arm.move_by('stretch_gripper', 0.0)
                self.robot.push_command()

            self.robot.pimu.runstop_event_trigger()
        else:
            self.robot.pimu.runstop_event_reset()

        response.success = True,
        response.message = 'is_runstopped: {0}'.format(request.data)
        return response

    ########### ROS Setup #######
    def ros_setup(self):
        self.node_name = self.get_name()

        self.get_logger().info("For use with S T R E T C H (TM) RESEARCH EDITION from Hello Robot Inc.")

        self.get_logger().info("{0} started".format(self.node_name))

        self.declare_parameter('mode', 'position')
        self.declare_parameter('broadcast_odom_tf', False)
        self.declare_parameter('controller_calibration_file', 'not_set')
        self.declare_parameter('timeout', 1.0)
        self.declare_parameter('rate', 15.0)
        self.declare_parameter('use_fake_mechaduinos', False)
        self.declare_parameter('fail_out_of_range_goal', True)
        # self.set_parameters_callback(self.parameter_callback)

        mode = self.get_parameter('mode').value
        self.get_logger().info('mode = ' + str(mode))

        self.broadcast_odom_tf = self.get_parameter('broadcast_odom_tf').value
        self.get_logger().info('broadcast_odom_tf = ' + str(self.broadcast_odom_tf))
        if self.broadcast_odom_tf:
            self.tf_broadcaster = tf2_ros.TransformBroadcaster(self)

        large_ang = 45.0 * np.pi/180.0

        filename = self.get_parameter('controller_calibration_file').value
        self.get_logger().info('Loading controller calibration parameters for the head from YAML file named {0}'.format(filename))
        with open(filename, 'r') as fid:
            controller_parameters = yaml.safe_load(fid)

            self.get_logger().info('controller parameters loaded = {0}'.format(controller_parameters))

            self.head_tilt_calibrated_offset_rad = controller_parameters['tilt_angle_offset']
            ang = self.head_tilt_calibrated_offset_rad
            if (abs(ang) > large_ang):
                self.get_logger().info('WARNING: self.head_tilt_calibrated_offset_rad HAS AN UNUSUALLY LARGE MAGNITUDE')
            self.get_logger().info('self.head_tilt_calibrated_offset_rad in degrees = {0}'.format(np.degrees(self.head_tilt_calibrated_offset_rad)))

            self.head_pan_calibrated_offset_rad = controller_parameters['pan_angle_offset']
            ang = self.head_pan_calibrated_offset_rad
            if (abs(ang) > large_ang):
                self.get_logger().info('WARNING: self.head_pan_calibrated_offset_rad HAS AN UNUSUALLY LARGE MAGNITUDE')
            self.get_logger().info('self.head_pan_calibrated_offset_rad in degrees = {0}'.format(np.degrees(self.head_pan_calibrated_offset_rad)))

            self.head_pan_calibrated_looked_left_offset_rad = controller_parameters['pan_looked_left_offset']
            ang = self.head_pan_calibrated_looked_left_offset_rad
            if (abs(ang) > large_ang):
                self.get_logger().info('WARNING: self.head_pan_calibrated_looked_left_offset_rad HAS AN UNUSUALLY LARGE MAGNITUDE')
            self.get_logger().info('self.head_pan_calibrated_looked_left_offset_rad in degrees = {0}'.format(np.degrees(self.head_pan_calibrated_looked_left_offset_rad)))

            self.head_tilt_backlash_transition_angle_rad = controller_parameters['tilt_angle_backlash_transition']
            self.get_logger().info('self.head_tilt_backlash_transition_angle_rad in degrees = {0}'.format(np.degrees(self.head_tilt_backlash_transition_angle_rad)))

            self.head_tilt_calibrated_looking_up_offset_rad = controller_parameters['tilt_looking_up_offset']
            ang = self.head_tilt_calibrated_looking_up_offset_rad
            if (abs(ang) > large_ang):
                self.get_logger().info('WARNING: self.head_tilt_calibrated_looking_up_offset_rad HAS AN UNUSUALLY LARGE MAGNITUDE')
            self.get_logger().info('self.head_tilt_calibrated_looking_up_offset_rad in degrees = {0}'.format(np.degrees(self.head_tilt_calibrated_looking_up_offset_rad)))

            self.wrist_extension_calibrated_retracted_offset_m = controller_parameters['arm_retracted_offset']
            m = self.wrist_extension_calibrated_retracted_offset_m
            if (abs(m) > 0.05):
                self.get_logger().info('WARNING: self.wrist_extension_calibrated_retracted_offset_m HAS AN UNUSUALLY LARGE MAGNITUDE')
            self.get_logger().info('self.wrist_extension_calibrated_retracted_offset_m in meters = {0}'.format(self.wrist_extension_calibrated_retracted_offset_m))

        self.linear_velocity_mps = 0.0 # m/s ROS SI standard for cmd_vel (REP 103)
        self.angular_velocity_radps = 0.0 # rad/s ROS SI standard for cmd_vel (REP 103)

        self.max_arm_height = 1.1

        self.odom_pub = self.create_publisher(Odometry, 'odom', 1)

        self.power_pub = self.create_publisher(BatteryState, 'battery', 1)
        self.calibration_pub = self.create_publisher(Bool, 'is_calibrated', 1)
        self.mode_pub = self.create_publisher(String, 'mode', 1)

        self.imu_mobile_base_pub = self.create_publisher(Imu, 'imu_mobile_base', 1)
        self.magnetometer_mobile_base_pub = self.create_publisher(MagneticField, 'magnetometer_mobile_base', 1)
        self.imu_wrist_pub = self.create_publisher(Imu, 'imu_wrist', 1)

        self.create_subscription(Twist, "cmd_vel", self.set_mobile_base_velocity_callback, 1)

        # ~ symbol gets parameter from private namespace
        self.joint_state_rate = self.get_parameter('rate').value
        self.timeout_s = self.get_parameter('timeout').value
        self.timeout = Duration(seconds=self.timeout_s)
        self.get_logger().info("{0} rate = {1} Hz".format(self.node_name, self.joint_state_rate))
        self.get_logger().info("{0} timeout = {1} s".format(self.node_name, self.timeout_s))

        self.use_fake_mechaduinos = self.get_parameter('use_fake_mechaduinos').value
        self.get_logger().info("{0} use_fake_mechaduinos = {1}".format(self.node_name, self.use_fake_mechaduinos))

        self.base_frame_id = 'base_link'
        self.get_logger().info("{0} base_frame_id = {1}".format(self.node_name, self.base_frame_id))
        self.odom_frame_id = 'odom'
        self.get_logger().info("{0} odom_frame_id = {1}".format(self.node_name, self.odom_frame_id))

        self.robot = rb.Robot()
        self.robot.startup()

        # TODO: check with the actuators to see if calibration is required
        #self.calibrate()

        self.joint_state_pub = self.create_publisher(JointState, 'joint_states', 1)

        self.last_twist_time = self.get_clock().now()

        # start action server for joint trajectories
        self.fail_out_of_range_goal = self.get_parameter('fail_out_of_range_goal').value
        self.joint_trajectory_action = JointTrajectoryAction(self)
        self.diagnostics = StretchDiagnostics(self, self.robot)

        if mode == "position":
            self.turn_on_position_mode()
        elif mode == "navigation":
            self.turn_on_navigation_mode()
        elif mode == "manipulation":
            self.turn_on_manipulation_mode()

        self.switch_to_manipulation_mode_service = self.create_service(Trigger,
                                                                       '/switch_to_manipulation_mode',
                                                                       self.manipulation_mode_service_callback)

        self.switch_to_navigation_mode_service = self.create_service(Trigger,
                                                                     '/switch_to_navigation_mode',
                                                                     self.navigation_mode_service_callback)

        self.switch_to_position_mode_service = self.create_service(Trigger,
                                                                   '/switch_to_position_mode',
                                                                   self.position_mode_service_callback)

        self.stop_the_robot_service = self.create_service(Trigger,
                                                          '/stop_the_robot',
                                                          self.stop_the_robot_callback)

        self.calibrate_the_robot_service = self.create_service(Trigger,
                                                               '/calibrate_the_robot',
                                                               self.calibrate_callback)

        self.runstop_service = self.create_service(SetBool,
                                                   '/runstop',
                                                   self.runstop_service_callback)

        timer_period = 1.0 / self.joint_state_rate
        self.timer = self.create_timer(timer_period, self.command_mobile_base_velocity_and_publish_state)

    def parameter_callback(self, parameters):
        self.get_logger().warn('Dynamic parameters not available yet')


def main():
    try:
        rclpy.init()
        executor = MultiThreadedExecutor(num_threads=2)
        node = StretchBodyNode()
        executor.add_node(node)
        executor.spin()
    except (KeyboardInterrupt, ThreadServiceExit):
        node.robot.stop()


if __name__ == '__main__':
    main()
