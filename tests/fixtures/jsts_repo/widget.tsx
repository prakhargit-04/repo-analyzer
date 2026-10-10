import React from 'react';
import { User } from './types';

interface WidgetProps {
  user: User;
}

export const UserWidget: React.FC<WidgetProps> = ({ user }) => {
  return (
    <div className="widget">
      <span>{user.name}</span>
    </div>
  );
};
