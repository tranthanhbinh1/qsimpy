"""
QSimPy 0.1.0 - Gymnasium Environment
Author: Hoa Nguyen
Sample Gymasium environment for QSimPy with the scenario of 5 IBM QNodes (washington, kolkata, hanoi, perth, lagos)
and continuous QTasks arrival, generated from a quantum circuit dataset.
"""

import gymnasium as gym
from gymnasium.spaces import Box, Discrete
import numpy as np
from numpy.random import default_rng
from qsimpy import Broker, QTask, TaskStatus, IBMQNode, Dataset
import simpy


class QSimPyEnv(gym.Env):
    MAX_ROUNDS = 999  # maximum number of rounds in the QTask dataset

    def __init__(self, dataset=None, config=None):
        self.dataset = dataset
        self.config = config

    class GymEnvQSimPy:
        """
        Gym environment for QSimPy.

        Args:
            config (dict): Configuration parameters for the environment.
            dataset (str): Path to the QTask dataset.

        Attributes:
            n_qtasks (int): Number of qtasks.
            n_qnodes (int): Number of qnodes.
            qtasks (list): List of qtasks.
            qnodes (list): List of qnodes.
            obs_dim (int): Dimension of the observation space.
            observation_space (gym.spaces.Box): Observation space.
            action_space (gym.spaces.Discrete): Action space.
            qtask_dataset (Dataset): QTasks dataset.
            rng (numpy.random.Generator): Random number generator.
            qsp_env (simpy.Environment): QSimPy environment.
            round (int): Current round.
            seed (int): Seed for the random number generator.
        """

        def __init__(
            self,
            config=None,
            dataset=None,
        ):
            """
            Initialize the GymEnvQSimPy class.

            Args:
                config (dict): Configuration parameters for the environment.
                dataset (str): Path to the dataset.
            """

            super().__init__()

            # OBSERVATION SPACE
            # Each observation is a dict of qtask_attributes and qnode_attributes
            # QTask attrributes = [arrivaltime, qt_qubits, cl]
            # QNode attributes = [qn_qubits, d1cps, next_available_time]
            self.n_qtasks = 25
            self.n_qnodes = 5  # number of qnodes
            self.qtasks = []
            self.qnodes = []

            self.obs_dim = 4 + self.n_qnodes * 3
            self.observation_space = Box(
                low=np.ones((self.obs_dim,), dtype=np.float32) * -np.inf,
                high=np.ones((self.obs_dim,), dtype=np.float32) * np.inf,
                dtype=np.float32,
            )
            # Example max values for each type of observation
            max_time = 10000000  # Max next availble time
            max_qubits = 500  # Max number of qubits
            max_layers = 1000000  # Max number of layers in a circuit
            max_clops = 10000  # Max computational load
            max_rescheduling_count = 1000  # Max number of rescheduling

            # Assuming the observation consists of [arrival_time, qubit_number, circuit_layers] for tasks
            # and [qubit_number, clops, next_available_time] for each node
            task_obs_low = np.array([0, 0, 0, 0], dtype=np.float64)
            task_obs_high = np.array(
                [max_time, max_qubits, max_layers, max_rescheduling_count],
                dtype=np.float64,
            )
            node_obs_low = np.array([0, 0, -1] * self.n_qnodes, dtype=np.float64)
            node_obs_high = np.array(
                [max_qubits, max_clops, max_time] * self.n_qnodes, dtype=np.float64
            )

            # Combine to form the complete observation space
            obs_low = np.concatenate([task_obs_low, node_obs_low]).astype(np.float64)
            obs_high = np.concatenate([task_obs_high, node_obs_high]).astype(np.float64)

            self.observation_space = Box(low=obs_low, high=obs_high, dtype=np.float64)
            self.current_obs = None

            # ACTION SPACE
            self.action_space = Discrete(self.n_qnodes)

            # Load QTasks dataset
            if dataset is None:
                raise ValueError("Dataset is not specified")
            self.qtask_dataset = Dataset(dataset)
            self.rng = default_rng(seed=22)
            # QSimPy environment
            self.qsp_env = simpy.Environment()
            self.setup_quantum_resources()

            # Round
            self.round = 1
            self.seed = 22

    def _get_obs(self):
        """
        Get the current observation of the environment.

        Returns:
            np.ndarray: The current observation, which includes the observation of the current quantum task and all quantum nodes.
        """
        # Get the current observation of quantum task
        if self.current_qtask is None:
            self.qtask_obs = np.array([0, 0, 0, 0], dtype=np.float64)
        else:
            self.qtask_obs = np.array(
                [
                    self.current_qtask.arrival_time,
                    self.current_qtask.qubit_number,
                    self.current_qtask.circuit_layers,
                    self.current_qtask.rescheduling_count,
                ],
                dtype=np.float64,
            )

        # Get the current observation of quantum nodes
        self.qnode_obs = []
        for qnode in self.qnodes:
            qnode_obs = np.array(
                [
                    qnode.qubit_number,
                    qnode.clops,
                    qnode.next_available_time,
                ],
                dtype=np.float64,
            )
            self.qnode_obs.append(qnode_obs)

        # Flatten the qnode observations and concatenate with qtask observations
        qnode_obs_flat = np.concatenate(self.qnode_obs).astype(np.float64)
        self.current_obs = np.concatenate(
            (self.qtask_obs, qnode_obs_flat), dtype=np.float64
        )
        return self.current_obs

    def setup_quantum_resources(self):
        # Create a list of 10 IBM QNodes
        qnode_ids = range(self.n_qnodes)
        qnode_names = [
            "washington",
            "kolkata",
            "hanoi",
            "perth",
            "lagos",
        ]
        self.qnodes = [
            IBMQNode.create_ibmq_node(self.qsp_env, qid, qname)
            for qid, qname in zip(qnode_ids, qnode_names)
        ]

        # Create a Broker
        self.broker = Broker(self.qsp_env, self.qnodes)

    def generate_qtasks(self):
        """Generate a list of QTasks from the QTask dataset, following Poisson distribution of arrival time."""
        # QTask IDs
        qtask_ids = list(
            f"{self.round:04d}" + f"{id:02d}" for id in range(self.n_qtasks)
        )

        # Get QTask from the subset of the dataset
        qtasks = self.qtask_dataset.get_subset_data(self.round)

        n_qtasks = len(qtasks)  # number of qtasks
        qtask_arrival = self.rng.uniform(
            low=0.1 + self.round * 60, high=59.9 + self.round * 60, size=n_qtasks
        )
        # Set the arrival time of the first qtask to 0
        qtask_arrival.sort()

        # Extract only the values (dictionaries) from qtasks
        qtask_values = list(qtasks.values())

        self.qtasks = [
            QTask(
                id=tid,
                arrival_time=arrival_time,
                qtask_data=qdata,
            )
            for tid, arrival_time, qdata in zip(qtask_ids, qtask_arrival, qtask_values)
        ]

        # Set current qtask to the first qtask in the list
        if len(self.qtasks) > 0:
            self.current_qtask = self.qtasks.pop(0)
        self.round += 1

    def submit_task_to_qnode(self, qtask, qnode_id):
        reward = 0
        qtask, waiting_time, execution_time = self.broker.preprocess_qtask(
            qtask, self.qnodes[qnode_id]
        )
        if qtask.status == TaskStatus.ERROR:
            # Apply large penalty to the reward if QTask constraints are not satisfied
            # Beside, this task need to be rescheduled to another QNode until it can be executed
            # Put this task back to the queue
            qtask.status = TaskStatus.QUEUED
            qtask.QNode = None
            qtask.rescheduling_count += 1
            qtask.arrival_time += 1
            # Find the index to insert the qtask based on arrival_time
            index = 0
            while (
                index < len(self.qtasks)
                and self.qtasks[index].arrival_time < qtask.arrival_time
            ):
                index += 1
            self.qtasks.insert(index, qtask)
            return -0.1, qtask.rescheduling_count
        # Submit the qtask to the qnode following the action
        qtask_execution = self.broker.submit_qtask_to_qnode(
            qtask, self.qnodes[qnode_id]
        )
        self.qsp_env.process(qtask_execution)
        # print(f"Estimated waiting time: {waiting_time}")
        # print(f"Estimated execution time: {execution_time}")
        reward = waiting_time + execution_time
        return reward, qtask.rescheduling_count

    def reset(self, *, seed=None, options=None):
        super().reset(seed=22)
        self.generate_qtasks()
        self.current_obs = self._get_obs().astype(np.float32)
        info = {}
        return self.current_obs, info

    def step(self, action):
        # Submit the current qtask to the selected qnode
        # action is qnode_id
        # Intermediately reward is the inverse of completion time
        # Sample Objective: Minimize the total completion time of all qtasks
        time_reward, _ = self.submit_task_to_qnode(self.current_qtask, action)
        reward = 1 / time_reward

        # Get the next observation
        # Check if there are more qtasks, if yes, get the next qtask, otherwise set terminated to True
        if len(self.qtasks) > 0:
            self.current_qtask = self.qtasks.pop(0)
            terminated = False
        else:
            self.current_qtask = None
            terminated = True

        self.current_obs = self._get_obs()

        return self.current_obs, reward, terminated, False, {}

    def close(self):
        pass
