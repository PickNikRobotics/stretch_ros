from control_msgs.action import FollowJointTrajectory
from trajectory_msgs.msg import JointTrajectory
from trajectory_msgs.msg import MultiDOFJointTrajectory
from geometry_msgs.msg import Twist
import rclpy
from rclpy.action import ActionServer
from rclpy.node import Node
import time


class FollowJointTrajectoryActionServer(Node):

    def __init__(self):
        super().__init__('follow_joint_trajectory_action_server')
        self._joint_trajectory_publisher = self.create_publisher(JointTrajectory, '/joint_trajectory', 10)
        self._cmd_vel_publisher = self.create_publisher(Twist, '/cmd_vel', 10)
        self._action_server = ActionServer(
            self,
            FollowJointTrajectory,
            '/stretch_controller/follow_joint_trajectory',
            self.execute_callback)

    def execute_callback(self, goal_handle):
        self.get_logger().info('Executing goal...')
        result = FollowJointTrajectory.Result()
        trajectory = goal_handle.request.trajectory
        multidof_trajectory = goal_handle.request.multi_dof_trajectory
        # print(multidof_trajectory)
        cmd_vel = Twist()
        previous_time_from_start = 0.0
        self._joint_trajectory_publisher.publish(trajectory)
        # print(trajectory)
        for point in multidof_trajectory.points:
            current_time_from_start = point.time_from_start.sec + point.time_from_start.nanosec * 1e-9
            # cmd_vel.linear.x = float(point.velocities[0].linear.x)
            # cmd_vel.angular.z = float(point.velocities[0].angular.z)
            cmd_vel = point.velocities[0]
            # print(cmd_vel)
            self._cmd_vel_publisher.publish(cmd_vel)
            execution_time = current_time_from_start - previous_time_from_start
            # print(execution_time)
            time.sleep(execution_time)
            previous_time_from_start = current_time_from_start
        cmd_vel.linear.x = 0.0
        cmd_vel.angular.z = 0.0
        self._cmd_vel_publisher.publish(cmd_vel)
        goal_handle.succeed()
        return result

def main(args=None):
    rclpy.init(args=args)
    follow_joint_trajectory_action_server = FollowJointTrajectoryActionServer()
    rclpy.spin(follow_joint_trajectory_action_server)

if __name__ == '__main__':
    main()
