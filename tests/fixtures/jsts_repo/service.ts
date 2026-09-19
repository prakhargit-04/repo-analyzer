import { User } from './types';

export interface Identifiable {
  getId(): string;
}

export interface UserService extends Identifiable {
  getUser(id: string): User;
}

export class UserServiceImpl implements UserService {
  private id: string;

  constructor(id: string) {
    this.id = id;
  }

  getId(): string {
    return this.id;
  }

  getUser(id: string): User {
    return { id, name: 'Test' };
  }
}

export const formatUser = (user: User): string => {
  return `${user.id}: ${user.name}`;
};
