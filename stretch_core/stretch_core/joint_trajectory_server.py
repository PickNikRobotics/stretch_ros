#! /usr/bin/env python
from __future__ import print_function

import traceback

from control_msgs.action import FollowJointTrajectory
from control_msgs.msg import JointComponentTolerance

from hello_helpers.hello_misc import to_sec

import rclpy
from rclpy.action import ActionServer

from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

from .action_exceptions import FollowJointTrajectoryException, GoalToleranceException, PathToleranceException
from .action_exceptions import InvalidGoalException, InvalidJointException
from .command_groups import HeadPanCommandGroup, HeadTiltCommandGroup, \
                            WristYawCommandGroup, GripperCommandGroup, \
                            TelescopingCommandGroup, LiftCommandGroup, \
                            MobileBaseCommandGroup
from .trajectory_components import get_trajectory_components


def merge_arm_joints(trajectory):
    new_trajectory = JointTrajectory()
    arm_indexes = []
    for index, name in enumerate(trajectory.joint_names):
        if 'joint_arm_l' in name:
            arm_indexes.append(index)
        else:
            new_trajectory.joint_names.append(name)

    # If individual arm joints are not present, the original trajectory is fine
    if not arm_indexes:
        return trajectory

    if 'wrist_extension' in trajectory.joint_names:
        raise InvalidJointException('Received a command for the wrist_extension joint and one or more '
                                    'telescoping_joints. These are mutually exclusive options. '
                                    f'The joint names in the received command = {trajectory.joint_names}')

    if len(arm_indexes) != 4:
        raise InvalidJointException('Commands with telescoping joints requires all telescoping joints to be present. '
                                    f'Only received len(arm_indexes) of 4 telescoping joints.')

    # Set up points and variables to track arm values
    total_extension = []
    arm_velocities = []
    arm_accelerations = []
    for point in trajectory.points:
        new_point = JointTrajectoryPoint()
        new_point.time_from_start = point.time_from_start
        new_trajectory.points.append(new_point)

        total_extension.append(0.0)
        arm_velocities.append([])
        arm_accelerations.append([])

    for index, name in enumerate(trajectory.joint_names):
        for point_index, point in enumerate(trajectory.points):
            x = point.positions[index]
            v = point.velocities[index] if index < len(point.velocities) else None
            a = point.accelerations[index] if index < len(point.accelerations) else None

            if index in arm_indexes:
                total_extension[point_index] += x
                if v is not None:
                    arm_velocities[point_index].append(v)
                if a is not None:
                    arm_accelerations[point_index].append(a)
            else:
                new_point = new_trajectory.points[point_index]
                new_point.positions.append(x)
                if v is not None:
                    new_point.velocities.append(v)
                if a is not None:
                    new_point.accelerations.append(a)

    # Now add the arm values
    new_trajectory.joint_names.append('wrist_extension')
    for point_index, new_point in enumerate(new_trajectory.points):
        new_point.positions.append(total_extension[point_index])
        vels = arm_velocities[point_index]
        accels = arm_accelerations[point_index]

        if vels:
            new_point.velocities.append(sum(vels) / len(vels))
        if accels:
            new_point.accelerations.append(sum(accels) / len(accels))

    return new_trajectory


def preprocess_gripper_trajectory(trajectory):
    gripper_joint_names = ['joint_gripper_finger_left', 'joint_gripper_finger_right', 'gripper_aperture']
    present_gripper_joints = list(set(gripper_joint_names) & set(trajectory.joint_names))

    # If no gripper joint names are present, no changes needed
    if not present_gripper_joints:
        return trajectory
    elif len(present_gripper_joints) == 2:
        if (gripper_joint_names[0] in present_gripper_joints and gripper_joint_names[1] in present_gripper_joints):
            # Make sure that all the points are the same
            left_index = trajectory.joint_names.index(gripper_joint_names[0])
            right_index = trajectory.joint_names.index(gripper_joint_names[1])
            for pt in trajectory.points:
                if pt.positions[left_index] != pt.positions[right_index]:
                    raise InvalidGoalException('Recieved a command that includes both the left and right gripper '
                                               'joints and their commanded positions are not the same. '
                                               f'{pt.position[left_index]} != {pt.position[right_index]}')
                # Due dilligence would also check the velocity/acceleration, but leaving for now

            # If all the points are the same, then we can safely eliminate one
            trajectory.joint_names = trajectory.joint_names[:right_index] + trajectory.joint_names[right_index + 1:]
            for pt in trajectory.points:
                pt.positions = pt.positions[:right_index] + pt.positions[right_index + 1:]
                if pt.velocity:
                    pt.velocity = pt.velocity[:right_index] + pt.velocity[right_index + 1:]
                if pt.acceleration:
                    pt.acceleration = pt.acceleration[:right_index] + pt.acceleration[right_index + 1:]
            present_gripper_joints = gripper_joint_names[:1]
        else:
            raise InvalidJointException('Recieved a command that includes an odd combination of gripper joints: '
                                        f'{present_gripper_joints}')
    elif len(present_gripper_joints) != 1:
        raise InvalidJointException('Recieved a command that includes too many gripper joints: '
                                    f'{present_gripper_joints}')

    gripper_index = trajectory.joint_names.index(present_gripper_joints[0])
    trajectory.joint_names[gripper_index] = 'stretch_gripper'
    return trajectory


class JointTrajectoryAction:

    def __init__(self, node, trajectory_rate, ignore_trajectory_velocities, ignore_trajectory_accelerations):
        self.node = node
        self.trajectory_rate = self.node.create_rate(trajectory_rate)
        self.ignore_trajectory_velocities = ignore_trajectory_velocities
        self.ignore_trajectory_accelerations = ignore_trajectory_accelerations

        self.server = ActionServer(self.node, FollowJointTrajectory, '/stretch_controller/follow_joint_trajectory',
                                   self.execute_cb)
        self.feedback = FollowJointTrajectory.Feedback()
        self.result = FollowJointTrajectory.Result()
        self.goal_handle = None

        r = self.node.robot
        head_pan_range_ticks = r.head.motors['head_pan'].params['range_t']
        head_pan_range_rad = (r.head.motors['head_pan'].ticks_to_world_rad(head_pan_range_ticks[1]),
                              r.head.motors['head_pan'].ticks_to_world_rad(head_pan_range_ticks[0]))
        head_tilt_range_ticks = r.head.motors['head_tilt'].params['range_t']
        head_tilt_range_rad = (r.head.motors['head_tilt'].ticks_to_world_rad(head_tilt_range_ticks[1]),
                               r.head.motors['head_tilt'].ticks_to_world_rad(head_tilt_range_ticks[0]))
        wrist_yaw_range_ticks = r.end_of_arm.motors['wrist_yaw'].params['range_t']
        wrist_yaw_range_rad = (r.end_of_arm.motors['wrist_yaw'].ticks_to_world_rad(wrist_yaw_range_ticks[1]),
                               r.end_of_arm.motors['wrist_yaw'].ticks_to_world_rad(wrist_yaw_range_ticks[0]))
        gripper_range_ticks = r.end_of_arm.motors['stretch_gripper'].params['range_t']
        gripper_range_rad = (r.end_of_arm.motors['stretch_gripper'].ticks_to_world_rad(gripper_range_ticks[0]),
                             r.end_of_arm.motors['stretch_gripper'].ticks_to_world_rad(gripper_range_ticks[1]))
        gripper_range_robotis = (r.end_of_arm.motors['stretch_gripper'].world_rad_to_pct(gripper_range_rad[0]),
                                 r.end_of_arm.motors['stretch_gripper'].world_rad_to_pct(gripper_range_rad[1]))

        self.head_pan_cg = HeadPanCommandGroup(head_pan_range_rad,
                                               self.node.head_pan_calibrated_offset_rad,
                                               self.node.head_pan_calibrated_looked_left_offset_rad)
        self.head_tilt_cg = HeadTiltCommandGroup(head_tilt_range_rad,
                                                 self.node.head_tilt_calibrated_offset_rad,
                                                 self.node.head_tilt_calibrated_looking_up_offset_rad,
                                                 self.node.head_tilt_backlash_transition_angle_rad)
        self.wrist_yaw_cg = WristYawCommandGroup(wrist_yaw_range_rad)
        self.gripper_cg = GripperCommandGroup(gripper_range_robotis)
        self.telescoping_cg = TelescopingCommandGroup(tuple(r.arm.params['range_m']),
                                                      self.node.wrist_extension_calibrated_retracted_offset_m)
        self.lift_cg = LiftCommandGroup(tuple(r.lift.params['range_m']))
        self.mobile_base_cg = MobileBaseCommandGroup(virtual_range_m=(-0.5, 0.5))

        self.trajectory_components = get_trajectory_components(r)

    def execute_cb(self, goal_handle):
        if self.node.robot_mode == 'manipulation':
            return self.execute_trajectory(goal_handle)

        self.goal_handle = goal_handle
        goal = goal_handle.request
        with self.node.robot_stop_lock:
            # Escape stopped mode to execute trajectory
            self.node.stop_the_robot = False
        self.node.robot_mode_rwlock.acquire_read()

        # For now, ignore goal time and configuration tolerances.
        commanded_joint_names = goal.trajectory.joint_names
        self.node.get_logger().info(("{0} joint_traj action: New trajectory received with joint_names = "
                                     "{1}").format(self.node.node_name, commanded_joint_names))

        ###################################################
        # Decide what to do based on the commanded joints.
        command_groups = [self.telescoping_cg, self.lift_cg, self.mobile_base_cg, self.head_pan_cg,
                          self.head_tilt_cg, self.wrist_yaw_cg, self.gripper_cg]
        updates = [c.update(commanded_joint_names, self.invalid_joints_callback,
                   robot_mode=self.node.robot_mode)
                   for c in command_groups]
        if not all(updates):
            # The joint names violated at least one of the command
            # group's requirements. The command group should have
            # reported the error.
            self.node.robot_mode_rwlock.release_read()
            return self.result

        num_valid_points = sum([c.get_num_valid_commands() for c in command_groups])
        if num_valid_points <= 0:
            err_str = ("Received a command without any valid joint names."
                       "Received joint names = {0}").format(commanded_joint_names)
            self.invalid_joints_callback(err_str)
            self.node.robot_mode_rwlock.release_read()
            return self.result
        elif num_valid_points != len(commanded_joint_names):
            err_str = ("Received only {0} valid joints out of {1} total joints. Received joint names = "
                       "{2}").format(num_valid_points, len(commanded_joint_names), commanded_joint_names)
            self.invalid_joints_callback(err_str)
            self.node.robot_mode_rwlock.release_read()
            return self.result

        ###################################################
        # Try to reach each of the goals in sequence until
        # an error is detected or success is achieved.
        for pointi, point in enumerate(goal.trajectory.points):
            self.node.get_logger().debug(("{0} joint_traj action: "
                                        "target point #{1} = <{2}>").format(self.node.node_name, pointi, point))

            valid_goals = [c.set_goal(point, self.invalid_goal_callback, self.node.fail_out_of_range_goal,
                                    manipulation_origin=self.node.mobile_base_manipulation_origin)
                        for c in command_groups]
            if not all(valid_goals):
                # At least one of the goals violated the requirements
                # of a command group. Any violations should have been
                # reported as errors by the command groups.
                self.node.robot_mode_rwlock.release_read()
                return self.result

            robot_status = self.node.robot.get_status() # uses lock held by robot
            [c.init_execution(self.node.robot, robot_status, backlash_state=self.node.backlash_state)
            for c in command_groups]
            self.node.robot.push_command()

            goals_reached = [c.goal_reached() for c in command_groups]
            goal_start_time = self.node.get_clock().now()

            while not all(goals_reached):
                if (self.node.get_clock().now() - goal_start_time) > self.node.default_goal_timeout_duration:
                    err_str = ("Time to execute the current goal point = <{0}> exceeded the "
                            "default_goal_timeout = {1}").format(point, self.node.default_goal_timeout_s)
                    self.goal_tolerance_violated_callback(err_str)
                    self.node.robot_mode_rwlock.release_read()
                    return self.result

                # Check if a premption request has been received.
                with self.node.robot_stop_lock:
                    if self.node.stop_the_robot or self.goal_handle.is_cancel_requested:
                        self.server.set_preempted()
                        self.node.get_logger().debug(("{0} joint_traj action: PREEMPTION REQUESTED, but not stopping "
                                                    "current motions to allow smooth interpolation between "
                                                    "old and new commands.").format(self.node.node_name))
                        self.node.stop_the_robot = False
                        self.node.robot_mode_rwlock.release_read()
                        return self.result

                robot_status = self.node.robot.get_status()
                named_errors = [c.update_execution(robot_status, success_callback=self.success_callback,
                                                backlash_state=self.node.backlash_state)
                                for c in command_groups]
                if any(ret == True for ret in named_errors):
                    self.node.robot_mode_rwlock.release_read()
                    return self.result

                self.feedback_callback(commanded_joint_names, point, named_errors)
                goals_reached = [c.goal_reached() for c in command_groups]
                rclpy.spin_once(self.node)

            self.node.get_logger().debug("{0} joint_traj action: Achieved target point.".format(self.node.node_name))

        self.success_callback("Achieved all target points.")
        self.node.robot_mode_rwlock.release_read()
        return self.result

    def invalid_joints_callback(self, err_str):
        if self.goal_handle.is_active or self.goal_handle.is_cancel_requested:
            self.node.get_logger().error("{0} joint_traj action: {1}".format(self.node.node_name, err_str))
            self.result.error_code = self.result.INVALID_JOINTS
            self.result.error_string = err_str
            self.goal_handle.abort()

    def invalid_goal_callback(self, err_str):
        if self.goal_handle.is_active or self.goal_handle.is_cancel_requested:
            self.node.get_logger().error("{0} joint_traj action: {1}".format(self.node.node_name, err_str))
            self.result.error_code = self.result.INVALID_GOAL
            self.result.error_string = err_str
            self.goal_handle.abort()

    def goal_tolerance_violated_callback(self, err_str):
        if self.goal_handle.is_active or self.goal_handle.is_cancel_requested:
            self.node.get_logger().error("{0} joint_traj action: {1}".format(self.node.node_name, err_str))
            self.result.error_code = self.result.GOAL_TOLERANCE_VIOLATED
            self.result.error_string = err_str
            self.goal_handle.abort()

    def feedback_callback(self, commanded_joint_names, desired_point, named_errors):
        clean_named_errors = []
        for named_error in named_errors:
            if type(named_error) == tuple:
                clean_named_errors.append(named_error)
            elif type(named_error) == list:
                clean_named_errors += named_error
        clean_named_errors_dict = dict((k, v) for k, v in clean_named_errors)

        actual_point = JointTrajectoryPoint()
        error_point = JointTrajectoryPoint()
        for i, commanded_joint_name in enumerate(commanded_joint_names):
            error_point.positions.append(clean_named_errors_dict[commanded_joint_name])
            actual_point.positions.append(desired_point.positions[i] - clean_named_errors_dict[commanded_joint_name])

        self.node.get_logger().debug("{0} joint_traj action: sending feedback".format(self.node.node_name))
        self.feedback.header.stamp = self.node.get_clock().now()
        self.feedback.joint_names = commanded_joint_names
        self.feedback.desired = desired_point
        self.feedback.actual = actual_point
        self.feedback.error = error_point
        self.goal_handle.publish_feedback(self.feedback)

    def success_callback(self, success_str):
        self.node.get_logger().info("{0} joint_traj action: {1}".format(self.node.node_name, success_str))
        self.result.error_code = self.result.SUCCESSFUL
        self.result.error_string = success_str
        self.goal_handle.succeed()

    def execute_trajectory(self, goal_handle):
        try:
            with self.node.robot_stop_lock:
                # Escape stopped mode to execute trajectory
                self.node.stop_the_robot = False
                self.node.robot_mode_rwlock.acquire_read()

            # Process the goal
            goal = goal_handle.request

            # Check for valid positions
            for i, pt in enumerate(goal.trajectory.points):
                if len(pt.positions) != len(goal.trajectory.joint_names):
                    raise InvalidGoalException(f'Goal point with index {i} has {len(pt.positions)} positions '
                                               f'but should have {len(goal.joint_names)}')

            goal.trajectory = merge_arm_joints(goal.trajectory)
            goal.trajectory = preprocess_gripper_trajectory(goal.trajectory)

            # Check for invalid names
            for index, name in enumerate(goal.trajectory.joint_names):
                if name not in self.trajectory_components:
                    raise InvalidJointException(f'Cannot find joint "{name}"')
            multi_dof_joints = goal.multi_dof_trajectory.joint_names
            if len(multi_dof_joints) > 1 or (multi_dof_joints and multi_dof_joints[0] != 'position'):
                raise InvalidJointException('Driver supports a single multi_dof joint named position. '
                                            f'Got {multi_dof_joints} instead.')
            for i, pt in enumerate(goal.multi_dof_trajectory.points):
                if len(pt.transforms) != len(goal.multi_dof_trajectory.joint_names):
                    raise InvalidGoalException(f'MultiDOF goal point with index {i} has {len(pt.transforms)} transforms '
                                               f'but should have {len(goal.joint_names)}')

            if self.ignore_trajectory_velocities or self.ignore_trajectory_accelerations:
                for pt in goal.trajectory.points:
                    if self.ignore_trajectory_velocities:
                        pt.velocities = []
                    if self.ignore_trajectory_accelerations:
                        pt.accelerations = []

            # Save the tolerances in a dictionary
            path_tolerance_dict = {tol.name: tol for tol in goal.path_tolerance}
            goal_tolerance_dict = {tol.name: tol for tol in goal.goal_tolerance}

            # Print the goal
            if goal.trajectory.points:
                dt = to_sec(goal.trajectory.points[-1].time_from_start)
                n_points = len(goal.trajectory.points)
            else:
                dt = to_sec(goal.multi_dof_trajectory.points[-1].time_from_start)
                n_points = len(goal.multi_dof_trajectory.points)

            n_joints = len(goal.trajectory.joint_names) + len(goal.multi_dof_trajectory.joint_names)
            self.node.get_logger().info(
                f'New follow_joint_trajectory goal with {n_points} points, {n_joints} joints over {dt} seconds.')

            for index, name in enumerate(goal.trajectory.joint_names):
                t_comp = self.trajectory_components[name]

                # Set Initial waypoint
                goal.trajectory.points[0].positions[index] = t_comp.get_position()
                if index < len(goal.trajectory.points[0].velocities):
                    goal.trajectory.points[0].velocities[index] = t_comp.get_velocity()

                t_comp.add_waypoints(goal.trajectory.points, index)

            if goal.multi_dof_trajectory.joint_names:
                self.trajectory_components['position'].add_waypoints(goal.multi_dof_trajectory.points, 0)

            start_time = self.node.get_clock().now()
            self.node.robot.start_trajectory()

            feedback = FollowJointTrajectory.Feedback()
            feedback.joint_names = goal.trajectory.joint_names
            feedback.multi_dof_joint_names = goal.multi_dof_trajectory.joint_names
            while rclpy.ok() and self.node.robot.is_trajectory_executing():
                now = self.node.get_clock().now()
                feedback.header.stamp = now.to_msg()
                feedback.desired.time_from_start = (now - start_time).to_msg()
                feedback.actual.time_from_start = feedback.desired.time_from_start
                feedback.error.time_from_start = feedback.desired.time_from_start
                feedback.desired.positions = []
                feedback.actual.positions = []
                feedback.error.positions = []

                dt = to_sec(feedback.desired.time_from_start)
                for joint_name in feedback.joint_names:
                    t_comp = self.trajectory_components[joint_name]
                    actual_pos = t_comp.get_position()
                    desired_pos = t_comp.get_desired_position(dt)

                    feedback.actual.positions.append(actual_pos)
                    feedback.desired.positions.append(desired_pos)
                    feedback.error.positions.append(actual_pos - desired_pos)

                if feedback.multi_dof_joint_names:
                    feedback.multi_dof_actual.time_from_start = feedback.desired.time_from_start
                    feedback.multi_dof_desired.time_from_start = feedback.desired.time_from_start

                    t_comp = self.trajectory_components['position']
                    actual_pos = t_comp.get_position()
                    desired_pos = t_comp.get_desired_position(dt)

                    feedback.multi_dof_actual.transforms = [actual_pos]
                    feedback.multi_dof_desired.transforms = [desired_pos]
                    # TODO: Compute the transform between the two transform positions
                    # feedback.multi_dof_error.transforms = [actual_pos - desired_pos]
                    # feedback.multi_dof_error.time_from_start = feedback.desired.time_from_start

                goal_handle.publish_feedback(feedback)

                # Check tolerances after publishing feedback
                self.check_tolerances(dt, path_tolerance_dict, goal.component_path_tolerance, is_path=True)
                self.trajectory_rate.sleep()

            self.node.robot.stop_trajectory()

            self.check_tolerances(dt, goal_tolerance_dict, goal.component_goal_tolerance, is_path=False)

            if goal.goal_time_tolerance != 0.0:
                # TODO: Check time tolerance
                pass

            goal_handle.succeed()
            return FollowJointTrajectory.Result(error_code=FollowJointTrajectory.Result.SUCCESSFUL,
                                                error_string='Achieved all target points.')

        except FollowJointTrajectoryException as e:
            self.node.get_logger().error(str(e))
            goal_handle.abort()
            return FollowJointTrajectory.Result(error_code=e.CODE, error_string=str(e))
        except Exception as e:
            self.node.robot.stop_trajectory()
            self.node.get_logger().error(str(traceback.format_exc()))
            goal_handle.abort()

            # There is no error code for "unknown error" so we just use -100.
            return FollowJointTrajectory.Result(error_code=-100, error_string=str(e))
        finally:
            self.node.robot_mode_rwlock.release_read()

    def check_tolerances(self, dt, tolerance_dict, component_tolerances, is_path=False):
        errors = []
        tolerance_type = 'path' if is_path else 'goal'

        # Check single DOF first
        for name, tolerance in tolerance_dict.items():
            t_comp = self.trajectory_components[name]
            # TODO: This code just uses the specified tolerances and ignores the "default". See
            # https://github.com/ros-controls/control_msgs/blob/galactic-devel/control_msgs/msg/JointTolerance.msg#L1
            # for more info

            actual = t_comp.get_position()
            desired = t_comp.get_desired_position(dt)

            diff = actual - desired
            if abs(diff) > tolerance.position:
                errors.append(f'Joint {name} exceeded {tolerance_type} tolerance: Actual: {actual:.3f} '
                              f'Desired: {desired:.3f} Tolerance: {tolerance.position:.3f}')

        # Check the multi_dof
        for component_tolerance in component_tolerances:
            t_comp = self.trajectory_components[component_tolerance.joint_name]
            actual = t_comp.get_position()
            desired = t_comp.get_desired_position(dt)
            if component_tolerance.component == JointComponentTolerance.TRANSLATION:
                # TODO: Compute euclidean
                diff = 0.0
                component = 'translation'
            elif component_tolerance.component == JointComponentTolerance.ROTATION:
                # TODO: Compute quaternion difference
                diff = 0.0
                component = 'translation'
            else:
                # X_AXIS=1, Y_AXIS=2, Z_AXIS=3
                component = ['', 'x', 'y', 'z'][component_tolerance.component]
                actual_component = getattr(actual.translation, component)
                desired_component = getattr(desired.translation, component)
                diff = desired_component - actual_component

            if diff > component_tolerance.position:
                errors.append(f'Joint {component_tolerance.joint_name} exceeded {tolerance_type} tolerance with '
                              f'the {component} component: Actual: {actual_component:.3f} '
                              f'Desired: {desired_component:.3f} Tolerance: {component_tolerance.position:.3f}')

        if not errors:
            return
        err_str = '/'.join(errors)
        if is_path:
            raise PathToleranceException(err_str)
        else:
            raise GoalToleranceException(err_str)
