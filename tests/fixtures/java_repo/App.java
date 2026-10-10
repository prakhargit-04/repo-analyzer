package com.example;

import java.util.List;
import static java.lang.Math.max;

public class App extends BaseApp implements Runnable {
    public App() {
        init();
    }

    public void run() {
        helper();
        System.out.println(max(1, 2));
    }

    public static class InnerClass extends BaseInner {
        public void innerMethod() {
            doWork();
        }
    }
}
