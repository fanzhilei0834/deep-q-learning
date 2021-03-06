import random
import zmq
from collections import deque

import gym
import numpy as np
from data_pb2 import Data
import tensorflow as tf
from tensorflow.keras.layers import Dense
from tensorflow.keras.models import Sequential
from tensorflow.keras.optimizers import Adam
from tensorflow.keras import backend as K
import horovod.tensorflow.keras as htk


class DQNAgent:
    def __init__(self, state_size, action_size):
        self.state_size = state_size
        self.action_size = action_size
        self.replay_buffer = deque(maxlen=2000)#创建最大长度为2000的双向队列
        self.gamma = 0.95  # Discount Rate
        self.epsilon = 1.0  # Exploration Rate
        self.epsilon_min = 0.01
        self.epsilon_decay = 0.995
        self.learning_rate = 0.001
        self.model = self._build_model()

    def _build_model(self):#创建一个三层的神经网络
        """Build Neural Net for Deep Q-learning Model"""

        model = Sequential()
        model.add(Dense(24, input_dim=self.state_size, activation='relu'))
        model.add(Dense(24, activation='relu'))
        model.add(Dense(self.action_size, activation='linear'))
        #model.compile(loss='mse', optimizer=Adam(lr=self.learning_rate))
        model.compile(loss='mse', optimizer=htk.DistributedOptimizer(Adam(lr=self.learning_rate)))
        return model

    def memorize(self, state, action, reward, next_state, done):#将信息加入replay_buffer
        self.replay_buffer.append((state, action, reward, next_state, done))

    def act(self, state):
        if np.random.rand() <= self.epsilon:#以概率epsilon随机决策
            return random.randrange(self.action_size)
        act_values = self.model.predict(state)#经过神经网络给出一个决策
        return np.argmax(act_values[0])  # returns action

    def replay(self, batch_size):
        minibatch = random.sample(self.replay_buffer, batch_size)#随机在replay_buffer中取batch_size个样本
        for state, action, reward, next_state, done in minibatch:
            target = reward
            if not done:
                target += self.gamma * np.amax(self.model.predict(next_state)[0])
            target_f = self.model.predict(state)
            target_f[0][action] = target
            self.model.fit(state, target_f, epochs=1, verbose=0)#训练网络
        if self.epsilon > self.epsilon_min:#每消耗batch_size个数据，epsilon减小一次
            self.epsilon *= self.epsilon_decay

    def save(self, name):
        self.model.save_weights(name)




if __name__ == '__main__':
    htk.init()
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    config.gpu_options.visible_device_list = str(htk.local_rank())
    K.set_session(tf.Session(config=config))


    env = gym.make('CartPole-v1')
    state_size = env.observation_space.shape[0]
    action_size = env.action_space.n

    agent = DQNAgent(state_size, action_size)
    # agent.load('./save/cartpole-dqn.h5')

    done = False#游戏结束标志
    batch_size = 32
    #num_episodes = 1000
    
    context = zmq.Context()
    socket = context.socket(zmq.REP)
    socket.bind("tcp://*:6659")

    counter = 1
    version = 1
    while True:

        #  Wait for next request from client
        #message = socket.recv()
        message = Data()
        message.ParseFromString(socket.recv())
        sendb = b''
        #print("Received request: %s" % message)
        agent.memorize(np.array(eval(message.state)), message.action, message.reward, np.array(eval(message.next_state)), message.done)

        #更新模型
        if len(agent.replay_buffer) > batch_size:
            agent.replay(batch_size)
            print("train epoch: ",counter)
            if counter % 10 == 0:
                agent.save('dqn_pra{}.h5'.format(version))
                fo = open('dqn_pra{}.h5'.format(version), 'rb')
                sendb = fo.read()
                fo.close()
                print('dqn_pra{}.h5 saved'.format(version))
                version += 1
            counter += 1
            
        #  Send reply back to client
        socket.send(sendb)
        
        