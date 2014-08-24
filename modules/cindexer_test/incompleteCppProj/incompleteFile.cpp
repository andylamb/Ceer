class C {
public:
  C() {}
  virtual ~C() {}

  static const int STATIC_CONST = 42;

  int m1(int p1, char* optional=(char*)0) {
    if (optional) {
      return p1 + (int)*optional;
    } else {
      return p1;
    }
  }

private:
  int privField;
};

int main(int argc, char** argv) {
  C c;
  c.
  C::
  C* cPtr = new C
  cPtr->

  return 42;
}
