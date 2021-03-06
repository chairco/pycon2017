import gym
import random
import cv2
import os
import numpy as np
import tensorflow as tf
from gym import wrappers
from collections import deque
from keras.models import Sequential
from keras.optimizers import RMSprop
from keras.layers import Dense, Flatten
from keras.layers.convolutional import Conv2D
from keras import backend as K

if not os.path.exists('./save_model'):
    os.makedirs('./save_model')

EPISODES = 2000
RENDER = False
MONITOR = True


class DQNAgent:
    def __init__(self, action_size):
        # environment settings
        self.state_size = (84, 84, 4)
        self.action_size = action_size
        # parameters about epsilon
        self.epsilon = 1.
        self.epsilon_start, self.epsilon_end = 1.0, 0.05
        self.epsilon_decay_step = 1.0 * (self.epsilon_start - self.epsilon_end) / 40000
        # parameters about training
        self.batch_size = 32
        self.train_start = 20000
        self.update_target_rate = 1000
        self.discount_factor = 0.99
        self.memory = deque(maxlen=40000)
        self.no_op_steps = 30
        # build model
        self.model = self.build_model()
        self.target_model = self.build_model()
        self.update_target_model()

        self.optimizer = self.optimizer()

        self.sess = tf.InteractiveSession()
        K.set_session(self.sess)

        self.avg_q_max, self.avg_loss = 0, 0
        self.sess.run(tf.global_variables_initializer())

    # if the error is in the interval [-1, 1], then the cost is quadratic to the error
    # But outside the interval, the cost is linear to the error
    def optimizer(self):
        a = K.placeholder(shape=(None, ), dtype='int32')
        y = K.placeholder(shape=(None, ), dtype='float32')

        py_x = self.model.output

        a_one_hot = K.one_hot(a, self.action_size)
        q_value = K.sum(py_x * a_one_hot, axis=1)
        error = K.abs(y - q_value)

        quadratic_part = K.clip(error, 0.0, 1.0)
        linear_part = error - quadratic_part
        loss = K.mean(0.5 * K.square(quadratic_part) + linear_part)

        optimizer = RMSprop(lr=0.01, epsilon=0.01)
        updates = optimizer.get_updates(self.model.trainable_weights, [], loss)
        train = K.function([self.model.input, a, y], [loss], updates=updates)

        return train

    # approximate Q function using Convolution Neural Network
    # state is input and Q Value of each action is output of network
    def build_model(self):
        model = Sequential()
        model.add(Conv2D(32, (8, 8), strides=(4, 4), activation='relu', input_shape=self.state_size))
        model.add(Conv2D(64, (4, 4), strides=(2, 2), activation='relu'))
        model.add(Conv2D(64, (3, 3), strides=(1, 1), activation='relu'))
        model.add(Flatten())
        model.add(Dense(512, activation='relu'))
        model.add(Dense(self.action_size))
        model.summary()
        return model

    # after some time interval update the target model to be same with model
    def update_target_model(self):
        self.target_model.set_weights(self.model.get_weights())

    # get action from model using epsilon-greedy policy
    def get_action(self, history):
        history = np.float32(history / 255.0)
        if np.random.rand() <= self.epsilon:
            return random.randrange(self.action_size)
        else:
            q_value = self.model.predict(history)
            return np.argmax(q_value[0])

    # save sample <s,a,r,s'> to the replay memory
    def remember(self, history, action, reward, next_history, dead):
        self.memory.append((history, action, reward, next_history, dead))

    # pick samples randomly from replay memory (with batch_size)
    def train_replay(self):
        if len(self.memory) < self.train_start:
            return
        if self.epsilon > self.epsilon_end:
            self.epsilon -= self.epsilon_decay_step

        mini_batch = random.sample(self.memory, self.batch_size)

        history = np.zeros((self.batch_size, self.state_size[0], self.state_size[1], self.state_size[2]))
        next_history = np.zeros((self.batch_size, self.state_size[0], self.state_size[1], self.state_size[2]))
        target = np.zeros((self.batch_size, ))
        action, reward, dead = [], [], []

        for i in range(self.batch_size):
            history[i] = np.float32(mini_batch[i][0] / 255.)
            next_history[i] = np.float32(mini_batch[i][3] / 255.)
            action.append(mini_batch[i][1])
            reward.append(mini_batch[i][2])
            dead.append(mini_batch[i][4])

        target_value = self.target_model.predict(next_history)
        
        for i in range(self.batch_size):
            if dead[i]:
                target[i] = reward[i]
            else:
                target[i] = reward[i] + self.discount_factor * np.amax(target_value[i])

        loss = self.optimizer([history, action, target])
        self.avg_loss += loss[0]

    def load_model(self, name):
        self.model.load_weights(name)

    def save_model(self, name):
        self.model.save_weights(name)


# 210*160*3(color) --> 84*84(mono)
# float --> integer (to reduce the size of replay memory)
def pre_processing(observe):
    observe = cv2.cvtColor(observe, cv2.COLOR_RGB2GRAY)
    processed_observe = np.uint8(cv2.resize(observe, (84, 84)) * 255)
    return processed_observe


if __name__ == "__main__":
    # In case of BreakoutDeterministic-v3, always skip 4 frames
    env = gym.make('BreakoutDeterministic-v3')
    if MONITOR:
        env = wrappers.Monitor(env, "./gym-results", force=True)
    # get size of action from environment
    action_size = env.action_space.n
    agent = DQNAgent(action_size)
    if os.path.exists('./save_model/Breakout_DQN.h5'):
        agent.load_model('./save_model/Breakout_DQN.h5')

    scores, episodes, global_step = [], [], 0
    
    for e in range(EPISODES):
        done = False
        dead = False
        # 1 episode = 5 lives
        step, score, start_life = 0, 0, 5
        observe = env.reset()

        # this is one of DeepMind's idea.
        # just do nothing at the start of episode to avoid sub-optimal
        for _ in range(random.randint(1, agent.no_op_steps)):
            observe, _, _, _ = env.step(1)

        # At start of episode, there is no preceding frame. So just copy initial states to make history
        state = pre_processing(observe)
        history = np.stack((state, state, state, state), axis=2)
        history = np.reshape([history], (1, 84, 84, 4))

        while not done:
            if RENDER:
                env.render()
            global_step += 1
            step += 1

            # get action for the current history and go one step in environment
            action = agent.get_action(history)
            observe, reward, done, info = env.step(action)
            # pre-process the observation --> history
            next_state = pre_processing(observe)
            next_state = np.reshape([next_state], (1, 84, 84, 1))
            next_history = np.append(next_state, history[:, :, :, :3], axis=3)

            agent.avg_q_max += np.amax(agent.model.predict(np.float32(history / 255.))[0])

            # if the ball is fall, then the agent is dead --> episode is not over
            if start_life > info['ale.lives']:
                dead = True
                start_life = info['ale.lives']

            reward = np.clip(reward, -1., 1.)

            # save the sample <s, a, r, s'> to the replay memory
            agent.remember(history, action, reward, next_history, dead)
            #agent.train_replay()
            # update the target model with model
            if global_step % agent.update_target_rate == 0:
                agent.update_target_model()

            score += reward

            # if agent is dead, then reset the history
            if dead:
                dead = False
            else:
                history = next_history

            if done:

                print("episode:", e, "  score:", score, "  memory length:", len(agent.memory),
                      "  epsilon:", agent.epsilon, "  global_step:", global_step, "  average_q:", agent.avg_q_max/float(step),
                      "  average loss:", agent.avg_loss/float(step))

                agent.avg_q_max, agent.avg_loss = 0, 0

        if e % 20 == 0:
            agent.save_model("./save_model/Breakout_DQN.h5")

