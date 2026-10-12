import { helper } from './utils';
const express = require('express');

class BaseController {
  constructor(name) {
    this.name = name;
  }
  log(msg) {
    console.log(msg);
  }
}

class UserController extends BaseController {
  getUser(req, res) {
    this.log('Getting user');
    const data = helper();
    return res.json(data);
  }
}

function createServer() {
  const app = express();
  return app;
}

const arrowHandler = (req, res) => {
  helper();
};

module.exports = { UserController, createServer, arrowHandler };
